"""Render deterministic role-profile prompt blocks."""

from __future__ import annotations

from .rolefiles import PROFILE_ORDER, ProfileSnapshot

PRECEDENCE_DECLARATION = """SOUL.md (정체성 치환)
└─ [고정 선언문] SOUL.md defines authoritative identity and voice bounds.
   mask.md may adapt surface style only where compatible with SOUL.
   On conflict, ignore mask and report it as a promotion/removal candidate;
   never reinterpret SOUL.
   └─ profile/mask.md → user.md → preferences.md → workflow.md → automation.md
      └─ "## What you know about the user" (vault 인덱스 = 검색용 이력)"""

_REPAIR_MARKER = "[profile block omitted: document exceeds its character budget; use /profile to repair]"
_TITLES = {
    "mask": "Mask",
    "user": "User",
    "preferences": "Preferences",
    "workflow": "Workflow",
    "automation": "Automation",
}


def render_profile_blocks(snapshot: ProfileSnapshot) -> str:
    """Render non-empty profile documents in fixed order.

    The output is byte-stable for a byte-identical snapshot: no timestamps,
    session ids, mtimes, aggregate revision, or other ambient state are emitted.
    """
    blocks: list[str] = []
    for name in PROFILE_ORDER:
        document = snapshot.documents.get(name)
        if document is None:
            continue
        guidance = _guidance(document.guidance)
        if _is_empty(guidance, document.used, document.limit):
            continue
        header = _header(name, document.used, document.limit)
        if _over_budget(document.used, document.limit):
            blocks.append(f"{header}\n{_REPAIR_MARKER}")
            continue
        blocks.append(f"{header}\n{guidance}")
    if not blocks:
        return ""
    return PRECEDENCE_DECLARATION + "\n\n" + "\n\n".join(blocks)


def _guidance(text: str) -> str:
    return text.strip()


def _is_empty(guidance: str, used: int, limit: int) -> bool:
    return not guidance and not _over_budget(used, limit)


def _over_budget(used: int, limit: int) -> bool:
    return used > limit


def _usage_percent(used: int, limit: int) -> int:
    if limit <= 0:
        return 0
    return min(999, (used * 100) // limit)


def _header(name: str, used: int, limit: int) -> str:
    percent = _usage_percent(used, limit)
    return f"### {_TITLES[name]} [{percent}% - {used}/{limit} chars]"
