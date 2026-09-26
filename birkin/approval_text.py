"""Korean presentation of approval records and resolution results.

Every approval surface (terminal review, workbench, dash, gateway, Telegram,
workspace) formats the same machine results. The stable English errors in
``approval_execution*.py`` remain the machine contract; this module maps them,
and the executor results, to one bounded Korean explanation plus a stable code
(docs/language-policy.md). Raw error text, receipt JSON and paths never become
the summary.

Pure functions only. Module-level imports are the stdlib and ``risk``; every
other Birkin module is imported lazily, and ``birkin.approvals`` never is, so
any surface can import this without an import cycle.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

from . import risk

Tone = Literal["success", "failure", "rejected", "info", "progress"]

# -- labels -------------------------------------------------------------------

CATEGORY_LABELS: Final[dict[str, str]] = {
    "memory": "기억 저장",
    "skill": "스킬 변경",
    "cron": "예약 작업",
    "work_item": "업무 항목",
    "connection": "Microsoft 365 연결",
    "mail_send": "메일 발송",
    "calendar_event": "일정 변경",
    "briefing_schedule": "브리핑 예약",
    "team_share": "팀 공유",
    "office_template": "Office 양식",
    "data_delete": "데이터 삭제",
    "moirai": "워크플로 실행",
    "workflow": "작업 계획",
    "harness": "하네스 변경",
    "worker": "작업자 실행",
    "shell": "Shell 명령",
    "operation": "차단된 작업 재실행",
    "office_create": "Office 문서 생성",
    "office_job": "Office 작업",
    "office_rollback": "Office 되돌리기",
    "office_batch": "Office 일괄 작업",
    "checkpoint_restore": "체크포인트 복원",
    "computer_use": "컴퓨터 제어",
    "companion": "후속 확인 예약",
    "question": "질문 답변",
}
UNKNOWN_CATEGORY_LABEL: Final = "기타 작업"

RISK_LABELS: Final[dict[str, str]] = {
    "low": "낮은 위험",
    "medium": "보통 위험",
    "high": "높은 위험",
    "critical": "매우 높은 위험",
}
UNKNOWN_RISK_LABEL: Final = "위험도 알 수 없음"

SURFACE_LABELS: Final[dict[str, str]] = {
    "gateway:telegram": "텔레그램",
    "gateway:slack": "Slack",
    "gateway:discord": "Discord",
    "gateway:http": "로컬 게이트웨이",
    "gateway:local": "로컬 게이트웨이",
    "gateway:voice": "음성",
    "terminal": "터미널",
    "web:dashboard": "웹 대시보드",
    "workspace:control": "작업 공간",
    "policy:auto-approve": "자동 승인 정책",
}

GATE_LABELS: Final[dict[str, str]] = {
    "tool_policy": "도구 정책",
    "hook_policy": "훅 정책",
    "fs_jail": "작업 공간 경로 제한",
    "network_file_policy": "네트워크 파일 경로 제한",
    "control_plane": "Birkin 제어 파일 보호",
    "local_temp_policy": "임시 폴더 접근 거부",
    "git_safe_directory": "Git 저장소 소유권",
    "powershell_execution_policy": "PowerShell 실행 정책",
    "powershell_opt_in": "PowerShell 사용 허용",
    "os_permission": "운영체제 권한",
}
UNKNOWN_GATE_LABEL: Final = "정책 차단"

_GATE_CONSEQUENCES: Final[dict[str, str]] = {
    "tool_policy": (
        "Birkin 정책으로 꺼진 도구입니다. 승인하면 이 요청 한 번만 정책 예외로 실행합니다."
    ),
    "hook_policy": (
        "훅 정책이 이 작업을 막았습니다. 승인하면 같은 입력으로 한 번 다시 시도하지만 "
        "훅이 다시 막으면 실행되지 않습니다."
    ),
    "fs_jail": "작업 공간 밖의 경로라 차단되었습니다. 승인하면 이 경로에 한 번만 접근합니다.",
    "network_file_policy": (
        "외부 전송 검사 중에는 네트워크 파일 경로를 쓸 수 없습니다. 승인하면 한 번만 접근합니다."
    ),
    "control_plane": (
        "Birkin 제어 파일을 바꾸려는 요청이라 차단되었습니다. 승인하면 한 번만 변경합니다."
    ),
    "local_temp_policy": (
        "기본 임시 폴더 접근이 거부되었습니다. 승인하면 작업 폴더 안 임시 폴더로 "
        "한 번 다시 실행합니다."
    ),
    "git_safe_directory": (
        "Git 저장소 소유권 정책이 명령을 막았습니다. 승인하면 이 저장소만 안전한 폴더로 "
        "지정해 한 번 다시 실행합니다."
    ),
    "powershell_execution_policy": (
        "PowerShell 실행 정책이 명령을 막았습니다. 승인하면 이 명령만 실행 정책을 우회해 "
        "한 번 실행합니다."
    ),
    "powershell_opt_in": (
        "PowerShell 사용이 허용되지 않았습니다. 승인하면 이 명령만 한 번 실행합니다."
    ),
    "os_permission": (
        "운영체제 권한 때문에 실패했습니다. 승인하면 같은 작업을 한 번 다시 시도합니다."
    ),
}
_DEFAULT_GATE_CONSEQUENCE: Final = (
    "Birkin 정책이 이 작업을 막았습니다. 승인하면 같은 입력으로 한 번만 다시 실행합니다."
)
_SHELL_EGRESS_NOTE: Final = " Shell 명령은 외부 전송(egress) 검사 없이 네트워크에 접근할 수 있습니다."

# -- shared copy ----------------------------------------------------------------

EMPTY_QUEUE: Final = "대기 중인 승인 요청이 없습니다."
CLAIMED: Final = "승인했습니다. 작업을 실행하는 중입니다."
REJECTED: Final = "거부했습니다. 작업은 실행되지 않습니다."
NEEDS_ANSWERS: Final = (
    "답변이 필요한 질문이라 여기서는 승인하거나 거부할 수 없습니다. "
    "질문을 보낸 화면에서 답변하세요."
)
FOLLOW_UP: Final = (
    "저장 위치에 같은 이름의 파일이 있어 저장하지 않았습니다. "
    "덮어쓰기 확인 요청을 새로 만들었으니 대기 목록에서 확인하세요."
)


def queue_heading(count: int) -> str:
    return f"승인 대기 {count}건 (위험도 높은 순)"


# -- record helpers -------------------------------------------------------------

_TARGET_CHARS: Final = 200
_TARGET_KEYS: Final = ("command", "path", "url", "query")


def category_label(category: object) -> str:
    return CATEGORY_LABELS.get(str(category or "").strip().lower(), UNKNOWN_CATEGORY_LABEL)


def risk_label(tier: object) -> str:
    return RISK_LABELS.get(str(tier or ""), UNKNOWN_RISK_LABEL)


def gate_label(gate: object) -> str:
    return GATE_LABELS.get(str(gate or ""), UNKNOWN_GATE_LABEL)


def needs_answers(record: Mapping[str, object]) -> bool:
    """A structured question: it is answered, never approved or rejected."""
    return (
        record.get("category") == "question"
        or record.get("action_state") == "action_needed"
    )


def headline(record: Mapping[str, object]) -> str:
    category = str(record.get("category") or "")
    label = category_label(category)
    title = str(record.get("title") or "").strip() or label
    return f"{risk_label(risk.risk_for(category))} · {label} — {title}"


def _redacted(value: str) -> str:
    from .workspace.redaction import redact_secrets

    return redact_secrets(value)


def _bounded_target(value: str) -> str:
    text = value.strip()
    if len(text) > _TARGET_CHARS:
        text = text[:_TARGET_CHARS] + "…"
    return _redacted(text)


def operation_target(tool_input: object) -> str:
    """What one blocked tool call touches: command, path, URL or query."""
    if not isinstance(tool_input, Mapping):
        return ""
    for key in _TARGET_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return _bounded_target(value)
    pairs = ", ".join(
        f"{key}={value}"
        for key, value in sorted(tool_input.items(), key=lambda item: str(item[0]))
        if isinstance(value, (str, int, float, bool))
    )
    return _bounded_target(pairs)


def request_target(record: Mapping[str, object]) -> str:
    """The concrete thing an approval acts on, bounded and secret-free."""
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return ""
    category = record.get("category")
    if category == "shell":
        command = payload.get("command")
        return _bounded_target(command) if isinstance(command, str) else ""
    if category == "operation":
        operation = payload.get("operation")
        if isinstance(operation, Mapping):
            return operation_target(operation.get("input"))
    return ""


def gate_consequence(gate: object, tool: object) -> str:
    """What approving one blocked operation does, in Korean."""
    text = _GATE_CONSEQUENCES.get(str(gate or ""), _DEFAULT_GATE_CONSEQUENCE)
    if gate == "tool_policy" and tool == "run_shell":
        text += _SHELL_EGRESS_NOTE
    return text


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _operation_summary(payload: Mapping[str, object]) -> str:
    operation = payload.get("operation")
    if not isinstance(operation, Mapping):
        return "↳ 요청 데이터가 올바르지 않습니다."
    tool = str(operation.get("tool", "?"))
    gate = str(operation.get("gate", "?"))
    cwd = str(operation.get("cwd", "?"))
    raw_input = _json_text(operation.get("input", {}))
    preview = raw_input[:1200]
    if len(raw_input) > len(preview):
        preview += f"… (전체 {len(raw_input)}자)"
    lines = [
        f"↳ 도구: {tool}",
        f"차단 단계: {gate_label(gate)} ({gate})",
        f"작업 폴더: {cwd}",
        f"입력: {preview}",
    ]
    environment = operation.get("environment")
    if isinstance(environment, Mapping) and environment:
        lines.append(
            "환경 변수: "
            + ", ".join(
                f"{key}={value}"
                for key, value in sorted(environment.items(), key=lambda item: str(item[0]))
            )
        )
    lines.append(f"무결성 digest: {str(payload.get('digest', ''))[:16]}")
    return "\n".join(lines)


def _office_summary(payload: Mapping[str, object]) -> str:
    lines: list[str] = []
    source = payload.get("source_filename")
    if isinstance(source, str) and source:
        lines.append(f"원본: {source}")
    destination = payload.get("destination")
    if isinstance(destination, str) and destination:
        lines.append(f"저장 위치: {destination}")
    outcome = payload.get("outcome")
    if isinstance(outcome, str) and outcome:
        lines.append(f"작업: {outcome[:200]}")
    overwrite = payload.get("overwrite_approved")
    if overwrite is True:
        lines.append("덮어쓰기: 주의: 기존 파일을 덮어쓸 수 있습니다")
    elif overwrite is False:
        lines.append("덮어쓰기: 안전: 기존 파일이 없어야 합니다")
    return ("↳ " + "\n".join(lines)) if lines else ""


_CARD_PREVIEW_CHARS: Final = 1200


def _card_preview(
    value: object,
    limit: int = _CARD_PREVIEW_CHARS,
    *,
    keep_newlines: bool = False,
) -> str:
    """Escaped, bounded text for a one-tap card; a cut always says so.

    Control and format characters (newline, bidi override, zero-width) are
    shown as escapes so a value cannot fake the following card lines or hide
    a suffix; ``keep_newlines`` keeps real line breaks for prose such as a
    mail body.
    """
    from .tools.connections import visible_text

    raw = str(value)
    if keep_newlines:
        text = "\n".join(visible_text(line) for line in raw.split("\n"))
    else:
        text = visible_text(raw)
    if len(text) <= limit:
        return text
    return (
        f"{text[:limit]}… (전체 {len(text)}자 중 {limit}자만 표시 · 전체 내용은 "
        "`birkin review` 또는 웹 승인 화면에서 확인하세요)"
    )


def payload_summary(
    category: str,
    payload: Mapping[str, object],
    *,
    fallback: bool = True,
) -> str:
    """The consequential part of a proposal, so a one-tap approve isn't blind.

    Categories without a dedicated summary fall back to bounded JSON; a surface
    that already shows the full data passes ``fallback=False`` to skip it.
    """
    if category == "shell":
        cwd = _card_preview(payload.get("cwd") or "")
        return (
            f"↳ 실행: {_card_preview(payload.get('command', ''))}\n"
            f"작업 폴더: {cwd or '지정 안 됨(Birkin 실행 위치)'}"
        )
    if category == "cron":
        from .cron_review import cron_review_lines

        return "↳ " + "\n".join(cron_review_lines(payload))
    if category == "skill":
        return f"↳ 스킬: {str(payload.get('name', payload.get('title', '')))[:120]}"
    if category == "moirai":
        return (
            f"↳ 워크플로우: {str(payload.get('script', ''))[:80]} · "
            f"할 일: {str(payload.get('task', ''))[:120]}"
        )
    if category == "workflow":
        raw_steps = payload.get("steps")
        steps = raw_steps if isinstance(raw_steps, list) else []
        return "↳ " + " → ".join(str(step)[:60] for step in steps[:4])
    if category == "operation":
        return _operation_summary(payload)
    if category == "mail_send":
        from .tools.connections import mail_send_review_text

        body = _card_preview(payload.get("body", ""), 600, keep_newlines=True)
        return f"↳ {mail_send_review_text(payload)}\n본문: {body}"
    if category == "calendar_event":
        from .tools.connections import calendar_event_review_text

        return f"↳ {calendar_event_review_text(payload)}"
    if category in {"office_job", "office_create"}:
        return _office_summary(payload)
    if not fallback or not payload:
        return ""
    return f"↳ 세부 데이터: {_card_preview(_json_text(payload))}"


def payload_detail(payload: object, limit: int | None = 600) -> str:
    """The full request data as a labelled, optionally bounded detail line."""
    text = _json_text(payload)
    if limit is not None and len(text) > limit:
        text = f"{text[:limit]}… (전체 {len(text)}자)"
    return f"세부 데이터: {text}"


def continuation_summary(value: object) -> str:
    """What runs after this approval; never raises on a malformed record."""
    from . import worker_hooks

    try:
        continuation = worker_hooks.validate(value)
    except worker_hooks.WorkerHookError:
        return "후속 작업 정보를 확인할 수 없습니다."
    context = continuation["context"]
    if continuation["handler"] == "moirai.resume.v1":
        return (
            f"moirai 실행 {context['run_id']}의 "
            f"{context['worker_id']}/{context['step_id']} 단계부터 이어서 진행합니다"
        )
    return f"{continuation['worker']} 작업을 저장된 지점부터 이어서 진행합니다"


# -- outcomes -------------------------------------------------------------------

GATEWAY_MARKS: Final[dict[Tone, str]] = {
    "success": "✅",
    "failure": "⚠",
    "rejected": "❌",
    "info": "ℹ️",
    "progress": "⏳",
}
TERMINAL_MARKS: Final[dict[Tone, str]] = {
    "success": "✓",
    "failure": "✗",
    "rejected": "✗",
    "info": "ℹ",
    "progress": "…",
}


@dataclass(frozen=True, slots=True)
class ApprovalOutcomeText:
    """One approval result as Korean copy plus its stable code."""

    tone: Tone
    code: str
    summary: str
    detail: str = ""
    ui_state: str = ""

    @property
    def ok(self) -> bool:
        return self.tone == "success"

    def render(
        self,
        marks: Mapping[Tone, str] = GATEWAY_MARKS,
        limit: int = 500,
    ) -> str:
        text = f"{marks[self.tone]} {self.summary}"
        if self.detail:
            text += f"\n{self.detail}"
        if len(text) > limit:
            text = text[: max(0, limit - 1)] + "…"
        return text


_ALREADY_RESOLVED = (
    "E_APPROVAL_ALREADY_RESOLVED",
    "이미 처리됐거나 찾을 수 없는 승인 요청입니다. 대기 목록을 다시 확인하세요.",
)
_STORE_BUSY = (
    "E_APPROVAL_STORE_BUSY",
    "승인 저장소가 사용 중이라 처리하지 못했습니다. 잠시 후 다시 시도하세요.",
)
_INTEGRITY = (
    "E_APPROVAL_INTEGRITY",
    "승인 실행 기록을 확인할 수 없어 안전을 위해 실행을 멈췄습니다. 작업을 다시 요청하세요.",
)
_FINALIZE_PENDING = (
    "E_APPROVAL_FINALIZE_PENDING",
    "작업은 실행됐을 수 있지만 결과 기록을 마치지 못했습니다. "
    "다시 승인하기 전에 결과를 확인하세요.",
)
_CONTINUATION_FAILED = (
    "E_APPROVAL_CONTINUATION_FAILED",
    "승인한 작업은 끝났지만 이어지는 후속 작업을 시작하지 못했습니다. 작업 기록을 확인하세요.",
)
_EXACT_ERRORS: Final[dict[str, tuple[str, str]]] = {
    "invalid approval id": (
        "E_APPROVAL_INVALID_ID",
        "승인 요청 ID가 올바르지 않습니다. 대기 목록에서 요청을 다시 선택하세요.",
    ),
    "not found or already resolved": _ALREADY_RESOLVED,
    "approval is not claimed": (
        "E_APPROVAL_NOT_CLAIMED",
        "실행을 기다리는 승인 요청이 아닙니다. 대기 목록을 다시 확인하세요.",
    ),
    "structured action requires answers": ("E_APPROVAL_NEEDS_ANSWERS", NEEDS_ANSWERS),
    "Telegram workflow requires its origin chat": (
        "E_APPROVAL_WORKFLOW_ORIGIN",
        "이 작업 계획은 요청한 텔레그램 채팅에서만 승인할 수 있습니다.",
    ),
    "approval store is busy": _STORE_BUSY,
    "cron store is busy; retry.": _STORE_BUSY,
    "cron store is busy": _STORE_BUSY,
    "approval payload is malformed": (
        "E_APPROVAL_PAYLOAD_MALFORMED",
        "승인 요청 데이터가 손상되어 실행을 멈췄습니다. 작업을 다시 요청하세요.",
    ),
    "approval execution state is missing": _INTEGRITY,
    "approval execution authority was changed": _INTEGRITY,
    "Office approval authority is incomplete": _INTEGRITY,
    "execution frozen": _INTEGRITY,
    "action outcome is unknown": (
        "E_APPROVAL_OUTCOME_UNKNOWN",
        "작업 실행 결과를 확인할 수 없습니다. "
        "같은 작업을 다시 승인하기 전에 결과를 직접 확인하세요.",
    ),
    "continuation is not pending": _CONTINUATION_FAILED,
}
_PREFIX_ERRORS: Final[tuple[tuple[str, tuple[str, str]], ...]] = (
    (
        "approval store is unavailable",
        (
            "E_APPROVAL_STORE_UNAVAILABLE",
            "승인 저장소를 읽을 수 없어 처리하지 못했습니다. "
            "디스크 상태를 확인한 뒤 다시 시도하세요.",
        ),
    ),
    ("approval execution could not be armed", _INTEGRITY),
    (
        "approval helper exited with status",
        (
            "E_APPROVAL_HELPER_EXITED",
            "승인 실행 도우미가 중간에 종료되었습니다. 잠시 후 대기 목록에서 상태를 확인하세요.",
        ),
    ),
    ("action recovery required", _FINALIZE_PENDING),
    ("action committed; approval finalization is pending", _FINALIZE_PENDING),
    ("action outcome persistence failed", _FINALIZE_PENDING),
    ("continuation failed", _CONTINUATION_FAILED),
)
_ACTION_FAILED_PREFIX: Final = "action failed:"
_ACTION_FAILED = (
    "E_APPROVAL_ACTION_FAILED",
    "승인한 작업을 실행하지 못했습니다. 요청 내용을 확인한 뒤 다시 요청하세요.",
)
_UNKNOWN = (
    "E_APPROVAL_UNKNOWN",
    "승인한 작업을 완료하지 못했습니다. 대기 목록에서 상태를 확인한 뒤 다시 시도하세요.",
)
_ACTION_NEEDED_CODES: Final = frozenset({
    "E_APPROVAL_OUTCOME_UNKNOWN",
    "E_APPROVAL_FINALIZE_PENDING",
})
_EXIT: Final = re.compile(r"\[exit (-?\d+)\]\s?(.*)\Z", re.S)
_OUTPUT_CHARS: Final = 300
_IN_PROGRESS: Final = frozenset({"approving", "executing", "resuming"})


def _failure(code: str, summary: str, detail: str = "") -> ApprovalOutcomeText:
    ui_state = "action_needed" if code in _ACTION_NEEDED_CODES else "failed"
    return ApprovalOutcomeText("failure", code, summary, detail, ui_state)


def _exit_outcome(match: re.Match[str]) -> ApprovalOutcomeText:
    code = int(match.group(1))
    output = _redacted(match.group(2).strip()[:_OUTPUT_CHARS])
    detail = f"출력: {output}" if output else ""
    if code == 0:
        return ApprovalOutcomeText(
            "success",
            "approved",
            "승인한 명령을 실행했습니다 (종료 코드 0).",
            detail,
            "succeeded",
        )
    return _failure(
        "command_failed",
        f"명령이 종료 코드 {code}(으)로 실패했습니다. 출력을 확인한 뒤 다시 요청하세요.",
        detail,
    )


def error_outcome(error: object) -> ApprovalOutcomeText:
    """Map a stable approval error (text or a result dict) to Korean copy.

    The raw error never becomes the summary: unknown text falls back to a
    bounded Korean message with ``E_APPROVAL_UNKNOWN``.
    """
    if isinstance(error, Mapping):
        if isinstance(error.get("follow_up_approval_id"), str):
            return ApprovalOutcomeText(
                "failure", "follow_up_required", FOLLOW_UP, ui_state="action_needed"
            )
        state = error.get("state")
        if isinstance(state, str) and isinstance(error.get("recheckable"), bool):
            # An unconfirmed mail send; its copy is owned by the mail module.
            from .approval_mail_outcome import unconfirmed_response

            return _failure(
                "E_APPROVAL_OUTCOME_UNKNOWN",
                str(unconfirmed_response(state)["error"]),
            )
        error = error.get("error")
    raw = str(error or "")
    exact = _EXACT_ERRORS.get(raw)
    if exact is not None:
        return _failure(*exact)
    for prefix, mapped in _PREFIX_ERRORS:
        if raw.startswith(prefix):
            return _failure(*mapped)
    if raw.startswith(_ACTION_FAILED_PREFIX):
        # A replayed operation fails with the tool's own "[exit N]" output.
        match = _EXIT.match(raw[len(_ACTION_FAILED_PREFIX):].strip())
        if match is not None and int(match.group(1)) != 0:
            return _exit_outcome(match)
        return _failure(*_ACTION_FAILED)
    return _failure(*_UNKNOWN)


def resolved_elsewhere(record: Mapping[str, object] | None) -> ApprovalOutcomeText:
    """Explain a record another surface (or policy) already resolved."""
    current = record or {}
    status = str(current.get("status") or "")
    via = str(current.get("approved_via") or current.get("rejected_via") or "")
    surface = SURFACE_LABELS.get(via) or SURFACE_LABELS.get(via.partition(":")[0], "")
    at = f"{surface}에서 " if surface else ""
    code = "answered_elsewhere"
    if status in {"approved", "resume_pending"}:
        return ApprovalOutcomeText(
            "info", code, f"{at}이미 승인되어 작업을 완료했습니다.", ui_state="succeeded"
        )
    if status in _IN_PROGRESS:
        return ApprovalOutcomeText(
            "info",
            code,
            f"{at}이미 승인되어 작업을 실행하고 있습니다. 잠시 후 결과를 확인하세요.",
            ui_state="running",
        )
    if status == "rejected":
        return ApprovalOutcomeText(
            "info", code, f"{at}이미 거부되어 작업을 실행하지 않았습니다.", ui_state="blocked"
        )
    if status == "expired":
        return ApprovalOutcomeText(
            "info",
            code,
            "승인 요청이 만료되어 작업을 실행하지 않았습니다. 필요하면 다시 요청하세요.",
            ui_state="blocked",
        )
    if status in {"error", "execution_frozen"}:
        return ApprovalOutcomeText(
            "failure",
            code,
            f"{at}승인했지만 작업을 완료하지 못했습니다. 작업 기록을 확인하세요.",
            ui_state="failed",
        )
    if status == "action_outcome_unknown":
        return ApprovalOutcomeText(
            "failure",
            code,
            f"{at}승인했지만 실행 결과를 확인할 수 없습니다. 다시 승인하기 전에 결과를 확인하세요.",
            ui_state="action_needed",
        )
    if status in {"answered", "consumed"}:
        return ApprovalOutcomeText(
            "info", code, "이미 답변한 질문입니다.", ui_state="succeeded"
        )
    return _failure(*_ALREADY_RESOLVED)


def _office_outcome(
    record: Mapping[str, object], text: str
) -> ApprovalOutcomeText | None:
    from .workspace.approval_receipts import OfficeReceiptProjection

    try:
        receipt = OfficeReceiptProjection.from_result(
            str(record.get("id") or ""), record, text
        )
    except (TypeError, ValueError):
        return None
    if receipt is None:
        return None
    detail = (
        f"저장 위치: {receipt.destination} · {receipt.validation_summary} · "
        f"{receipt.visual_validation_summary}"
    )
    if receipt.validation_summary == "구조 검증 실패":
        return _failure(
            "office_validation_failed",
            "문서를 저장했지만 구조 검증에 실패했습니다. 저장된 파일을 확인하세요.",
            detail,
        )
    return ApprovalOutcomeText(
        "success", "approved", "승인한 Office 작업을 완료했습니다.", detail, "succeeded"
    )


def _workflow_outcome(text: str) -> ApprovalOutcomeText:
    # The workflow receipt is already Korean user copy (moirai.outcome.render):
    # its status line carries the run's completion, and the report itself is
    # what the approver was waiting for. Only a complete run is a success.
    from .moirai.outcome import receipt_completion

    state = receipt_completion(text)
    if state == "complete":
        return ApprovalOutcomeText(
            "success", "approved", "승인한 워크플로를 실행했습니다.", text, "succeeded"
        )
    if state == "partial":
        return ApprovalOutcomeText(
            "failure",
            "workflow_partial",
            "승인한 워크플로가 일부만 완료되었습니다. 실패한 부분을 확인하세요.",
            text,
            "action_needed",
        )
    if state == "waiting":
        return ApprovalOutcomeText(
            "progress",
            "workflow_waiting",
            "승인한 워크플로가 질문에 대한 답을 기다리고 있습니다.",
            text,
            "action_needed",
        )
    if state:
        return _failure(
            "workflow_failed",
            "승인한 워크플로를 끝까지 실행하지 못했습니다. 결과를 확인하세요.",
            text,
        )
    return ApprovalOutcomeText(
        "info",
        "workflow_unconfirmed",
        "승인한 워크플로의 완료 여부를 확인할 수 없습니다. 결과를 확인하세요.",
        text,
        "action_needed",
    )


def approve_outcome(
    record: Mapping[str, object] | None,
    result: Mapping[str, object],
) -> ApprovalOutcomeText:
    """One approve result, read with the record as it stands afterwards."""
    from .approval_dispatch import (
        SHELL_CWD_MISSING_PREFIX,
        SHELL_EMPTY_RESULT,
        SHELL_TIMEOUT_RESULT,
    )

    if not result.get("ok"):
        if (
            result.get("error") == "not found or already resolved"
            and record is not None
            and record.get("status") != "pending"
        ):
            return resolved_elsewhere(record)
        return error_outcome(result)
    status = result.get("status")
    if not isinstance(status, str):
        status = str((record or {}).get("status") or "")
    if status in _IN_PROGRESS:
        return ApprovalOutcomeText(
            "progress",
            "running",
            "승인한 작업을 아직 실행하고 있습니다. 잠시 후 결과를 확인하세요.",
            ui_state="running",
        )
    text = str(result.get("result") or "")
    match = _EXIT.match(text)
    if match is not None:
        return _exit_outcome(match)
    if text == SHELL_TIMEOUT_RESULT:
        return _failure(
            "command_timed_out",
            "명령이 시간 제한을 넘겨 중단되었습니다. "
            "명령을 나누거나 시간 제한을 늘려 다시 요청하세요.",
        )
    if text == SHELL_EMPTY_RESULT:
        return _failure(
            "command_empty", "실행할 명령이 비어 있어 아무것도 실행하지 않았습니다."
        )
    if text.startswith(SHELL_CWD_MISSING_PREFIX):
        return _failure(
            "command_cwd_missing",
            "작업 폴더를 찾을 수 없어 명령을 실행하지 않았습니다. "
            "폴더를 확인한 뒤 다시 요청하세요.",
        )
    category = (record or {}).get("category")
    if record is not None and category in {"office_job", "office_create"}:
        office = _office_outcome(record, text)
        if office is not None:
            return office
    if category == "moirai" and text:
        return _workflow_outcome(text)
    if result.get("continuation_result") is not None:
        return ApprovalOutcomeText(
            "success",
            "approved",
            "승인한 작업과 이어지는 작업을 완료했습니다.",
            ui_state="succeeded",
        )
    return ApprovalOutcomeText(
        "success", "approved", "승인한 작업을 완료했습니다.", ui_state="succeeded"
    )


def reject_outcome(
    result: Mapping[str, object],
    record: Mapping[str, object] | None,
) -> ApprovalOutcomeText:
    if result.get("ok"):
        return ApprovalOutcomeText("rejected", "rejected", REJECTED, ui_state="blocked")
    if record is None:
        return _failure(*_ALREADY_RESOLVED)
    if record.get("status") == "pending":
        # Still pending after a refused reject: the store lock or disk failed.
        return _failure(*_STORE_BUSY)
    return resolved_elsewhere(record)


def decision_outcome(
    record: Mapping[str, object] | None,
    result: Mapping[str, object],
    *,
    approve: bool,
) -> ApprovalOutcomeText:
    """The outcome of one approve or reject decision."""
    if approve:
        return approve_outcome(record, result)
    return reject_outcome(result, record)


def record_outcome(record: Mapping[str, object]) -> ApprovalOutcomeText:
    """Project an already resolved record into the same outcome copy."""
    status = str(record.get("status") or "")
    if status == "approved":
        receipt = record.get("action_receipt")
        result: dict[str, object] = {
            "ok": True,
            "result": receipt if isinstance(receipt, str) else "",
        }
        continuation = record.get("continuation_result")
        if continuation is not None:
            result["continuation_result"] = continuation
        return approve_outcome(record, result)
    if status == "rejected":
        return ApprovalOutcomeText("rejected", "rejected", REJECTED, ui_state="blocked")
    if status == "error":
        if isinstance(record.get("follow_up_approval_id"), str):
            return error_outcome(record)
        if record.get("failure_stage") == "continuation":
            return _failure(*_CONTINUATION_FAILED)
        detail = str(record.get("execution_error") or "")
        if not detail.startswith(_ACTION_FAILED_PREFIX):
            detail = f"{_ACTION_FAILED_PREFIX} {detail}"
        return error_outcome(detail)
    return resolved_elsewhere(record)


__all__ = [
    "CATEGORY_LABELS",
    "CLAIMED",
    "EMPTY_QUEUE",
    "FOLLOW_UP",
    "GATE_LABELS",
    "GATEWAY_MARKS",
    "NEEDS_ANSWERS",
    "REJECTED",
    "RISK_LABELS",
    "SURFACE_LABELS",
    "TERMINAL_MARKS",
    "ApprovalOutcomeText",
    "approve_outcome",
    "category_label",
    "continuation_summary",
    "decision_outcome",
    "error_outcome",
    "gate_consequence",
    "gate_label",
    "headline",
    "needs_answers",
    "operation_target",
    "payload_detail",
    "payload_summary",
    "queue_heading",
    "record_outcome",
    "reject_outcome",
    "request_target",
    "resolved_elsewhere",
    "risk_label",
]
