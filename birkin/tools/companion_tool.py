"""Natural-language entry to Companion: the model proposes, a human approves.

The tool can only record a *candidate* and queue its activation in the
approval inbox (``birkin review`` / the gateway buttons) — the same hook every
consequential action passes through. It cannot activate, answer, or close a
commitment, and the state files themselves are control-plane-protected from
the file tools (see tools/files.py), so this really is the only door.
"""

from __future__ import annotations

from typing import Any

from . import Tool, ToolContext, ToolResult


def _propose(tool_input: dict[str, Any], ctx: ToolContext) -> ToolResult:
    from .. import companion
    try:
        status = companion.propose_checkin(
            outcome=str(tool_input.get("outcome", "")),
            check_in_at=str(tool_input.get("check_in_at", "")),
            next_action=str(tool_input.get("next_action", "")),
            context_id=str(tool_input.get("context_id", "")),
            cfg=ctx.cfg, origin="chat")
    except companion.CompanionError as exc:
        return ToolResult(f"Cannot propose a check-in: {exc}", is_error=True)
    if status.get("auto"):
        ok = bool(status.get("ok"))
        return ToolResult(("Scheduled: " if ok else "Could not schedule: ")
                          + str(status.get("result", "")), is_error=not ok)
    return ToolResult(
        f"Queued for the user's approval (id {status['id']}). "
        f"Nothing is scheduled unless they approve it.")


def tools() -> list[Tool]:
    return [Tool(
        name="companion_propose",
        description=(
            "Propose a follow-up check-in for something the user explicitly "
            "committed to do at an agreed time (e.g. \"remind me to ask about "
            "the draft Monday 9am\"). NOT executed now — it goes to the "
            "user's approval queue. Only for the user's own stated "
            "commitment, never for inferred ones. check_in_at must be ISO "
            "8601 with a UTC offset, e.g. 2026-08-01T09:00+09:00."),
        input_schema={"type": "object", "properties": {
            "outcome": {"type": "string",
                        "description": "what the user committed to"},
            "check_in_at": {"type": "string",
                            "description": "ISO 8601 with offset"},
            "next_action": {"type": "string",
                            "description": "the next concrete step, if named"},
            "context_id": {"type": "string",
                           "description": "telegram:<chat-id>; omit when one "
                                          "context is bound"}},
            "required": ["outcome", "check_in_at"]},
        fn=_propose)]
