"""Canonical Working Memory projection and workspace mutation authority."""

from __future__ import annotations

from typing import cast

from birkin import goals, harness

_PRIVATE_EVIDENCE_KEYS = frozenset({"path", "absolute_path", "source_path"})


def project_working_memory(
    session_id: str,
    files_evidence: tuple[dict[str, object], ...],
) -> dict[str, object]:
    """Combine canonical goal, Working Memory, and checkpoint evidence."""

    state = harness.working_state(session_id)
    goal = goals.get_active(session_id=session_id)
    projected_goal: dict[str, object] | None = None
    if goal is not None:
        projected_goal = {
            "slug": goal.slug,
            "objective": goal.objective,
            "tokens_used": goal.tokens_used,
            "status": goal.status,
        }
    return {
        "revision": int(state.get("revision") or 0),
        "goal": projected_goal,
        "fields": {
            field: list(cast(list[str], state.get(field) or []))
            for field in harness.WORKING_FIELDS
        },
        "files_evidence": [
            {
                key: value
                for key, value in item.items()
                if key.casefold() not in _PRIVATE_EVIDENCE_KEYS
            }
            for item in files_evidence
        ],
    }
