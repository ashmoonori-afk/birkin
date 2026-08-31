from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from typing import ClassVar, TypeAlias, TypeGuard, TypedDict

from pydantic import BaseModel, ConfigDict, ValidationError

from .. import config, store

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)


class StoredWorkflowPayload(TypedDict, total=False):
    chat_id: JsonValue
    task: JsonValue
    steps: JsonValue


class ProposalPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True)

    title: str
    summary: str
    steps: list[str]


class StoredWorkflow(TypedDict):
    category: str
    status: str
    payload: StoredWorkflowPayload


PROPOSAL_OPEN = "<birkin-work-proposal>"
PROPOSAL_CLOSE = "</birkin-work-proposal>"
ULTRAWORK_PREFACE = "ULTRAWORK MODE ENABLED!"
APPROVED_OPEN = "<birkin-approved-work>"
APPROVED_CLOSE = "</birkin-approved-work>"
DELIVERY_OPEN = "<telegram-delivery-contract>"
DELIVERY_CLOSE = "</telegram-delivery-contract>"
MARKET_DATA_OPEN = "<verified-market-data-policy>"
MARKET_DATA_CLOSE = "</verified-market-data-policy>"

DELIVERY_POLICY = (
    f"{DELIVERY_OPEN}\n"
    "Put the complete user-requested deliverable in the final Telegram reply. "
    "Telegram supports long replies by splitting them into multiple messages, so "
    "never replace requested content with a workspace file name or path. Do not "
    "create a report-only document unless the user explicitly asks for a file. "
    "Operational logs or test receipts may remain files, but report their result "
    "in the final reply.\n"
    f"{DELIVERY_CLOSE}\n"
)

MARKET_DATA_POLICY = (
    f"{MARKET_DATA_OPEN}\n"
    "For every current security, ETF, or index price, call market_quote for all "
    "symbols and use its exact price, currency, as_of timestamp, and source_url. "
    "Never present a search snippet, article value, analyst target, 52-week "
    "extreme, or remembered value as the current price. If market_quote fails or "
    "is stale, state that the current price is unavailable instead of guessing. "
    "Show the quote timestamp and distinguish live/intraday data from the latest "
    "close before calculating entry, exit, or target levels.\n"
    f"{MARKET_DATA_CLOSE}\n"
)

WORKFLOW_POLICY = (
    DELIVERY_POLICY
    + MARKET_DATA_POLICY
    + (
        "For this trusted Telegram turn, decide BEFORE using any tool whether the "
        "request is likely to take at least three minutes, needs multiple execution "
        "phases, or would use any subagent. If so, do not start the work or call a "
        "tool yet. Respond with exactly one proposal envelope and nothing else:\n"
        f"{PROPOSAL_OPEN}"
        '{"title":"short title","summary":"why this work is useful",'
        '"steps":["concrete step 1","concrete step 2"]}'
        f"{PROPOSAL_CLOSE}\n"
        "Use 1-8 concrete steps. Propose useful planning or workflows proactively "
        "when they materially help, but act directly on short, simple requests. "
        f"If the turn contains {APPROVED_OPEN}, the user already approved that exact "
        "proposal: execute it end-to-end now, including its approved subagents, and "
        "do not propose it again.\n"
    )
)


@dataclass(frozen=True, slots=True)
class WorkflowProposal:
    title: str
    summary: str
    steps: tuple[str, ...]
    preface: str = ""

    def render(self) -> str:
        lines = [f"🧭 {self.title}", self.summary, "", "승인할 실행 계획:"]
        lines.extend(f"{index}. {step}" for index, step in enumerate(self.steps, 1))
        lines.extend(["", "승인하면 이 대화에서 바로 실행합니다."])
        if self.preface:
            lines[:0] = [self.preface, ""]
        return "\n".join(lines)

    def render_html(self) -> str:
        steps = "\n".join(
            f"{index:02d}  {escape(step)}" for index, step in enumerate(self.steps, 1)
        )
        card = (
            f"<b>{escape(self.title)}</b>\n"
            f"{escape(self.summary)}\n\n"
            f"<b>실행 계획 · {len(self.steps)}단계</b>\n"
            f"<blockquote>{steps}</blockquote>\n"
            "아래에서 실행 여부를 선택해 주세요."
        )
        if self.preface:
            return f"<i>{escape(self.preface)}</i>\n\n{card}"
        return card


@dataclass(frozen=True, slots=True)
class WorkflowResolution:
    message: str
    resume_prompt: str | None = None


def _is_string_list(value: JsonValue | None) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _stored_workflow(raw: Mapping[str, JsonValue] | None) -> StoredWorkflow | None:
    if raw is None:
        return None
    category = raw.get("category")
    status = raw.get("status")
    payload = raw.get("payload")
    if not isinstance(category, str) or not isinstance(status, str):
        return None
    if not isinstance(payload, dict):
        return None
    stored_payload: StoredWorkflowPayload = {"chat_id": payload.get("chat_id", "")}
    if "task" in payload:
        stored_payload["task"] = payload["task"]
    if "steps" in payload:
        stored_payload["steps"] = payload["steps"]
    return {"category": category, "status": status, "payload": stored_payload}


def _workflow_plan(payload: StoredWorkflowPayload) -> tuple[str, list[str]] | None:
    task = payload.get("task")
    steps = payload.get("steps")
    if not isinstance(task, str) or not task.strip():
        return None
    if not _is_string_list(steps) or not all(step.strip() for step in steps):
        return None
    return task, steps


def _pending_id(raw: Mapping[str, JsonValue]) -> str:
    identifier = raw.get("id")
    return identifier if isinstance(identifier, str) else ""


def is_proposal_prefix(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped:
        return False
    if ULTRAWORK_PREFACE.startswith(stripped):
        return True
    if stripped.startswith(ULTRAWORK_PREFACE):
        stripped = stripped[len(ULTRAWORK_PREFACE) :].lstrip()
        if not stripped:
            return True
    return PROPOSAL_OPEN.startswith(stripped) or stripped.startswith(PROPOSAL_OPEN)


def has_reserved_marker(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            PROPOSAL_OPEN,
            PROPOSAL_CLOSE,
            APPROVED_OPEN,
            APPROVED_CLOSE,
        )
    )


def parse_proposal(text: str) -> WorkflowProposal | None:
    stripped = text.strip()
    preface = ""
    if stripped.startswith(ULTRAWORK_PREFACE):
        preface = ULTRAWORK_PREFACE
        stripped = stripped[len(ULTRAWORK_PREFACE) :].lstrip()
    if not (stripped.startswith(PROPOSAL_OPEN) and stripped.endswith(PROPOSAL_CLOSE)):
        return None
    body = stripped[len(PROPOSAL_OPEN) : -len(PROPOSAL_CLOSE)]
    try:
        payload = ProposalPayload.model_validate_json(body)
    except ValidationError:
        return None
    if not payload.title.strip():
        return None
    if not payload.summary.strip():
        return None
    if not 1 <= len(payload.steps) <= 8:
        return None
    if not all(step.strip() for step in payload.steps):
        return None
    return WorkflowProposal(
        title=payload.title.strip()[:100],
        summary=payload.summary.strip()[:500],
        steps=tuple(step.strip()[:200] for step in payload.steps),
        preface=preface,
    )


def queue_proposal(proposal: WorkflowProposal, task: str, chat_id: str) -> str:
    rec: Mapping[str, JsonValue] = store.add_pending(
        category="workflow",
        title=proposal.title,
        description=proposal.summary,
        payload={
            "chat_id": str(chat_id),
            "task": task.strip()[:4000],
            "steps": list(proposal.steps),
        },
        origin="telegram",
    )
    return _pending_id(rec)


def is_workflow(aid: str) -> bool:
    rec = _stored_workflow(store.get_pending(aid))
    return bool(rec and rec["category"] == "workflow")


def is_running(aid: str, chat_id: str) -> bool:
    rec = _stored_workflow(store.get_pending(aid))
    payload = rec["payload"] if rec else None
    return bool(
        rec
        and rec["category"] == "workflow"
        and rec["status"] == "running"
        and payload is not None
        and str(payload.get("chat_id", "")) == str(chat_id)
    )


def resolve_proposal(
    aid: str,
    chat_id: str,
    *,
    approve: bool,
    actor_id: str,
    via: str,
) -> WorkflowResolution:
    if not store.valid_pending_id(aid):
        return WorkflowResolution("⚠ 올바르지 않은 작업 제안 ID입니다.")
    path = config.pending_dir() / f"{aid}.json"
    try:
        with store.file_lock(path):
            rec = _stored_workflow(store.get_pending(aid))
            if not rec or rec["status"] != "pending":
                return WorkflowResolution("⚠ 이미 처리됐거나 찾을 수 없는 제안입니다.")
            if rec["category"] != "workflow":
                return WorkflowResolution("⚠ 작업 제안이 아닙니다.")
            payload = rec["payload"]
            if str(payload.get("chat_id", "")) != str(chat_id):
                return WorkflowResolution("⚠ 이 제안은 다른 채팅에 속합니다.")
            if not approve:
                _ = store.resolve_pending(
                    aid,
                    "rejected",
                    rejected_by=actor_id,
                    rejected_via=via,
                )
                store.append_activity(f"workflow[{aid}]: rejected via {via}")
                return WorkflowResolution("❌ 작업 제안을 거부했습니다.")
            plan = _workflow_plan(payload)
            if plan is None:
                _ = store.resolve_pending(
                    aid,
                    "error",
                    approved_by=actor_id,
                    approved_via=via,
                )
                return WorkflowResolution("⚠ 저장된 작업 제안이 손상됐습니다.")
            task, steps = plan
            _ = store.resolve_pending(
                aid,
                "claimed",
                approved_by=actor_id,
                approved_via=via,
            )
    except store.FileLockTimeout:
        return WorkflowResolution("⚠ 승인 저장소가 사용 중입니다. 다시 시도해 주세요.")

    plan = "\n".join(f"- {step}" for step in steps)
    resume = (
        f"{APPROVED_OPEN}\n"
        "The user approved this exact work plan. Execute it end-to-end now. "
        "Use subagents only where the approved plan benefits from them. Keep "
        "the user informed through concise progress updates.\n\n"
        f"Original request:\n{task}\n\nApproved plan:\n{plan}\n"
        f"{APPROVED_CLOSE}"
    )
    store.append_activity(f"workflow[{aid}]: approved via {via}")
    return WorkflowResolution("✅ 승인됨 — 작업을 시작합니다.", resume)


def _transition(
    aid: str, expected: set[str], status: str, chat_id: str | None = None
) -> bool:
    if not store.valid_pending_id(aid):
        return False
    path = config.pending_dir() / f"{aid}.json"
    try:
        with store.file_lock(path):
            rec = _stored_workflow(store.get_pending(aid))
            if (
                not rec
                or rec["category"] != "workflow"
                or rec["status"] not in expected
            ):
                return False
            payload = rec["payload"]
            if chat_id is not None and str(payload.get("chat_id", "")) != str(chat_id):
                return False
            _ = store.resolve_pending(aid, status)
    except store.FileLockTimeout:
        return False
    return True


def mark_running(aid: str, chat_id: str) -> bool:
    return _transition(aid, {"claimed"}, "running", chat_id)


def mark_interrupted(aid: str) -> bool:
    return _transition(aid, {"claimed", "running"}, "interrupted")


def finish(aid: str, status: str) -> bool:
    if status not in {"completed", "error"}:
        return False
    return _transition(aid, {"running"}, status)


def restore_claim(aid: str) -> bool:
    return _transition(aid, {"claimed"}, "pending")


def restore_stranded_claims() -> int:
    restored = 0
    for path in config.pending_dir().glob("*.json"):
        if restore_claim(path.stem):
            restored += 1
    return restored
