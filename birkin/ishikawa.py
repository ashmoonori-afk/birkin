"""Ishikawa debugging nudge (thinking-frameworks design, Item 6).

When the same tool fails repeatedly in the journal, the fix loop usually
narrows to one category of cause (the code, always the code) and stops
considering the rest. Ishikawa's fishbone is the classic correction: force at
least one hypothesis per fixed category before the next probe. This module is
a *nudge*, not a gate — it renders a short ASCII checklist for the prompt and
never blocks or rewrites anything. Stdlib only, ASCII only, fail-open.
"""

from __future__ import annotations

from typing import Any

# Fixed fishbone categories. Machine-consumed sentinels; keep this exact order.
CATEGORIES = ("code", "environment", "input-data", "timing", "permissions",
              "external-service")

TRIGGER = 2  # >= this many failures sharing a tool surface the note
WINDOW = 5   # how many recent failures to look at


def shared_tool(failures: list[dict[str, Any]]) -> str | None:
    """The tool >= TRIGGER of the failures share, else None.

    "Tool" is the call's label, else role, else phase; a failure without any
    of the three counts toward nothing.
    """
    counts: dict[str, int] = {}
    for failure in failures or []:
        if not isinstance(failure, dict):
            continue
        tool = str(failure.get("label") or failure.get("role")
                   or failure.get("phase") or "").strip()
        if not tool:
            continue
        counts[tool] = counts.get(tool, 0) + 1
        if counts[tool] >= TRIGGER:
            return tool
    return None


def render_note(tool: str) -> str:
    """The ASCII checklist for one repeated failure surface."""
    lines = [
        "ISHIKAWA DEBUGGING CHECKLIST",
        f"Tool '{tool}' failed {TRIGGER}+ times recently. Before probing "
        "again, write one hypothesis for EACH category:",
    ]
    lines.extend(f"- [ ] {category}" for category in CATEGORIES)
    lines.append("Test the cheapest plausible hypothesis first; do not "
                 "retry the identical action.")
    return "\n".join(lines)


def ishikawa_note(failures: list[dict[str, Any]] | None = None) -> str:
    """The nudge, or "" when the trigger is not met. Never raises.

    ``failures`` are moirai-journal call rows (the same rows
    ``runtime.failure_context`` renders); None reads them from the journal.
    """
    try:
        if failures is None:
            from .moirai import journal
            failures = journal.recent_failed_calls(WINDOW)
        tool = shared_tool(failures)
        return render_note(tool) if tool else ""
    except Exception:
        return ""
