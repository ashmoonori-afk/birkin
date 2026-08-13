"""Reconnect recovery: the surface rebuilds purely from authority state.

The workbench holds no client-side truth: every snapshot re-reads approvals,
runs and jobs from the store, so a UI restart (or a dropped daemon
connection) recovers by simply snapshotting again. These tests prove the
queue reflects store mutations made *by the authority* between snapshots —
the UI never caches a resolved approval back to life.
"""
from __future__ import annotations

from birkin import store, workbench


class _Session:
    cfg = {"model": "m", "provider": "p"}


def _ledger_ids(snap) -> dict[str, str]:
    return {it["id"]: it["view"].state
            for it in workbench.build_ledger(snap)
            if it["kind"] == "approval"}


def test_snapshot_recovers_pending_after_restart(tmp_path, monkeypatch):
    rec = store.add_pending(category="cron", title="재접속 복구 검증",
                            description="d", payload={})
    try:
        snap = workbench.snapshot(_Session())
        assert _ledger_ids(snap).get(rec["id"]) == "waiting_human"

        # authority resolves it while the UI is "down"
        store.resolve_pending(rec["id"], "rejected")

        # a fresh snapshot (= reconnect) must not resurrect it as pending
        snap2 = workbench.snapshot(_Session())
        assert _ledger_ids(snap2).get(rec["id"]) != "waiting_human"
    finally:
        store.resolve_pending(rec["id"], "rejected")


def test_ledger_never_marks_unresolved_as_completed(tmp_path):
    rec = store.add_pending(category="cron", title="완료 위조 금지",
                            description="d", payload={})
    try:
        snap = workbench.snapshot(_Session())
        state = _ledger_ids(snap).get(rec["id"])
        assert state == "waiting_human"
        assert state != "completed"
    finally:
        store.resolve_pending(rec["id"], "rejected")
