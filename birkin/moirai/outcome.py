"""What a finished workflow run means, and how it reads to a person.

The engine's ``status`` only says whether ``main(m)`` returned. A hard task
whose every worker died still returns, so "completed" used to reach the user
as success. This module is the single place that turns a run summary into an
honest completion (complete, partial, failed, aborted, waiting), an exit code,
and the Korean text the CLI, an approval receipt and a chat reply all show.

Pure on purpose: no birkin imports, so any surface can call it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Optional

# What a script (or the engine on its behalf) may declare about its own work.
COMPLETIONS = ("complete", "partial", "failed")

COMPLETION_LABELS = {
    "complete": "완료",
    "partial": "일부 완료",
    "failed": "실패",
    "aborted": "중단",
    "waiting": "입력 대기",
}

_ICONS = {
    "complete": "✅",
    "partial": "⚠️",
    "failed": "❌",
    "aborted": "⏹️",
    "waiting": "⏸️",
}

# The keys a pattern's structured result keeps its human-readable report in.
_BODY_KEYS = ("answer", "final", "report", "summary")
_DETAIL_CHARS = 1200

NO_RESULT = "워크플로우가 결과를 만들지 못했어요."
WAITING = "워크플로우가 질문에 대한 답을 기다리고 있어요. 승인 목록에서 답해 주세요."
TRUNCATED = "… 결과가 길어 앞부분만 담았어요."


def completion(out: Mapping[str, Any]) -> str:
    """The run's completion: the status first, then what the work declared."""
    status = str(out.get("status") or "")
    if status == "aborted":
        return "aborted"
    if status == "waiting_input":
        return "waiting"
    if status != "completed":
        return "failed"
    declared = out.get("completion")
    if declared in COMPLETIONS:
        return str(declared)
    result = out.get("result")
    if isinstance(result, Mapping):
        if result.get("completion") in COMPLETIONS:
            return str(result["completion"])
        if result.get("error"):
            return "failed"
    return "complete"


def receipt_completion(text: str) -> str:
    """The completion a rendered receipt's status line shows, or "".

    An approval keeps only the rendered text, so this reads the icon
    ``render`` put first; a text it did not render yields "".
    """
    for state, icon in _ICONS.items():
        if text.startswith(icon.rstrip("\ufe0f")):
            return state
    return ""


def exit_code(out: Mapping[str, Any]) -> int:
    """0 when at least part of the work got done, 1 otherwise."""
    return 0 if completion(out) in ("complete", "partial") else 1


def render(out: Mapping[str, Any], *, name: str = "",
           limit: Optional[int] = None) -> str:
    """Status line, the result itself, then the run id.

    With ``limit``, only the result body is cut (and says so); the status
    line and the run id always survive, because they are what a person needs
    to judge the result and find the full record.
    """
    state = completion(out)
    head = _status_line(out, state, name)
    run_id = str(out.get("run_id") or "")
    tail = f"실행 기록: {run_id}" if run_id else ""
    middle = "\n\n".join(
        part for part in (_body(out, state), *_sections(out)) if part)
    text = "\n\n".join(part for part in (head, middle, tail) if part)
    if limit is None or len(text) <= limit:
        return text
    # head + "\n\n" + cut + "\n" + TRUNCATED + "\n\n" + tail
    room = max(0, limit - len(head) - len(tail) - len(TRUNCATED) - 5)
    cut = middle[:room].rstrip()
    middle = f"{cut}\n{TRUNCATED}" if cut else TRUNCATED
    return "\n\n".join(part for part in (head, middle, tail) if part)


def _count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, (list, tuple)):
        return len(value)
    return 0


def _status_line(out: Mapping[str, Any], state: str, name: str) -> str:
    line = f"{_ICONS[state]} 워크플로우 {COMPLETION_LABELS[state]}"
    if name:
        line += f" ({name})"
    if "agents" in out:
        line += f" · 에이전트 {_count(out.get('agents'))}명"
    failures = _count(out.get("failures"))
    if failures > 0:
        line += f" · 실패 {failures}건"
    seconds = out.get("seconds")
    if isinstance(seconds, (int, float)) and not isinstance(seconds, bool):
        line += f" · {round(float(seconds), 1):g}초"
    return line


def _body(out: Mapping[str, Any], state: str) -> str:
    if state == "waiting":
        return WAITING
    result = out.get("result")
    if result is None:
        return NO_RESULT if state == "failed" else ""
    if isinstance(result, str):
        return result.strip() or (NO_RESULT if state == "failed" else "")
    if isinstance(result, Mapping):
        for key in _BODY_KEYS:
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        if result.get("error") or state == "failed":
            return NO_RESULT
        if "completion" in result:
            # A declared-completion contract carries its explanation in the
            # sections below; dumping it again as JSON would only repeat it.
            return ""
    detail = json.dumps(result, ensure_ascii=False, default=str)
    if len(detail) > _DETAIL_CHARS:
        detail = detail[:_DETAIL_CHARS] + " …"
    return f"세부 결과:\n{detail}"


def _sections(out: Mapping[str, Any]) -> list[str]:
    """The research contract's caveats, which must travel with its answer."""
    result = out.get("result")
    if not isinstance(result, Mapping):
        return []
    blocks: list[str] = []
    ledger = result.get("claim_ledger")
    unresolved = [
        str(claim.get("claim"))
        for claim in (ledger if isinstance(ledger, list) else [])
        if isinstance(claim, Mapping)
        and claim.get("status") in {"unresolved", "refuted"}
    ]
    if unresolved:
        blocks.append("미확정 또는 반박된 항목:\n"
                      + "\n".join(f"- {claim}" for claim in unresolved))
    raw_reasons = result.get("reasons")
    reasons = [str(reason)
               for reason in (raw_reasons if isinstance(raw_reasons, list) else [])]
    if reasons:
        blocks.append("남은 제약:\n" + "\n".join(f"- {reason}" for reason in reasons))
    basis = str(result.get("verification_basis") or "").strip()
    if basis:
        blocks.append(f"검증 기준: {basis}")
    return blocks
