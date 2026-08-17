"""Canonical Working Memory and goal bridge for checkpoint snapshots."""

from __future__ import annotations

from dataclasses import asdict

from . import goals, harness
from .checkpoints import CanonicalStateSnapshot


def snapshot(session_id: str) -> CanonicalStateSnapshot:
    goal = goals.get_active(session_id=session_id)
    return CanonicalStateSnapshot(
        session_id=session_id,
        working_memory=harness.working_state(session_id),
        goal=asdict(goal) if goal is not None else None,
    )


def restore(session_id: str, state: CanonicalStateSnapshot) -> None:
    if state["session_id"] != session_id:
        raise ValueError("checkpoint belongs to a different session")
    current = harness.working_state(session_id)
    _ = goals.validate_snapshot(state["goal"], session_id=session_id)
    expected_revision = int(current.get("revision") or 0)
    restored = harness.restore_working(
        session_id,
        state["working_memory"],
        expected_revision=expected_revision,
    )
    if not restored:
        raise ValueError("working memory changed during checkpoint restore")
    try:
        goals.restore_snapshot(state["goal"], session_id=session_id)
    except BaseException:
        rollback_revision = int(
            harness.working_state(session_id).get("revision") or 0
        )
        if not harness.restore_working(
            session_id,
            current,
            expected_revision=rollback_revision,
        ):
            raise RuntimeError(
                "goal restore failed and working memory rollback failed"
            )
        raise
