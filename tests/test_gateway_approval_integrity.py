from __future__ import annotations

import threading

import pytest

from birkin import approval_execution, approvals, config, cron, store
from birkin.approval_execution_codec import JSONValue
from birkin.approval_execution_types import EventSink
from birkin.gateway import workflow
from birkin.gateway.channels.telegram import TelegramChannel
from birkin.tools import ToolContext, build_registry


def test_claimed_action_executes_only_its_stored_payload(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    rec = store.add_pending(
        category="note",
        title="stored",
        description="",
        payload={"value": "stored"},
        origin="test",
    )
    assert approvals.claim(rec["id"], approved_by="human:test", approved_via="test")["ok"] is True
    executed: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        approvals,
        "execute_action",
        lambda category, payload: executed.append((category, payload)) or "done",
    )

    result = approval_execution.execute_claimed(rec["id"], approvals.execute_action)

    assert result["ok"] is True
    assert executed == [("note", {"value": "stored"})]
    assert store.get_pending(rec["id"])["status"] == "approved"


def test_generic_approval_surfaces_hide_telegram_workflows(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    workflow.queue_proposal(
        workflow.WorkflowProposal("workflow", "telegram only", ("run",)),
        "task",
        "42",
    )
    generic = store.add_pending(
        category="note",
        title="generic",
        description="",
        payload={},
        origin="test",
    )

    visible = approvals.reviewable_pending()

    assert [rec["id"] for rec in visible] == [generic["id"]]


def test_generic_approval_worker_has_a_dedicated_slot(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()

    class _Gateway:
        @staticmethod
        def claim_action(_aid, **identity):
            assert identity == {
                "actor_id": "human:telegram:42",
                "via": "gateway:telegram",
            }
            return "running", True

        @staticmethod
        def execute_claimed_action(_aid):
            started.set()
            release.wait(timeout=2)
            return "done"

    channel = TelegramChannel("token", allowed_chat_ids=["42"])
    monkeypatch.setattr(channel, "_call", lambda *_args, **_kwargs: {"ok": True})
    callback = {
        "id": "cb",
        "data": f"apv:{'a' * 12}",
        "from": {"id": 42},
        "message": {"chat": {"id": 42}, "message_id": 1, "text": "action"},
    }

    channel._handle_callback(_Gateway(), callback)
    assert started.wait(timeout=2)

    assert "42" in channel._action_workers
    assert "42" not in channel._workers
    worker = channel._action_workers["42"]
    release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()


def test_native_subagent_tool_requires_approved_gateway_work(tmp_path) -> None:
    ctx = ToolContext(
        cfg={},
        client=None,
        cwd=tmp_path,
        subagent_approval_required=True,
        approved_work=False,
    )

    result = build_registry(ctx).execute("spawn_subagent", {"task": "inspect"})

    assert result.is_error is True
    assert "approved" in result.content.lower()


@pytest.mark.parametrize(
    ("transition", "initial_status", "expected"),
    [
        ("claim", "pending", {"ok": False, "error": "approval store is busy"}),
        (
            "execute_claimed",
            "approving",
            {"ok": False, "error": "approval store is busy"},
        ),
        ("restore_claim", "approving", False),
        ("reject", "pending", {"ok": False}),
    ],
)
def test_approval_transitions_preserve_busy_contract_on_lock_timeout(
    tmp_path, monkeypatch, transition, initial_status, expected
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    rec = store.add_pending(
        category="note", title="locked", description="", payload={}, origin="test"
    )
    if initial_status != "pending":
        store.resolve_pending(rec["id"], initial_status)
    pending_path = config.pending_dir() / f"{rec['id']}.json"
    before = pending_path.read_bytes()

    class _TimeoutLock:
        def __enter__(self):
            raise store.FileLockTimeout("busy")

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(store, "file_lock", lambda _path: _TimeoutLock())

    resolver_kwargs = {
        "claim": {"approved_by": "human:test", "approved_via": "test"},
        "reject": {"rejected_by": "human:test", "rejected_via": "test"},
    }
    result = getattr(approvals, transition)(
        rec["id"],
        **resolver_kwargs.get(transition, {}),
    )

    assert result == expected
    assert pending_path.read_bytes() == before
    assert store.get_pending(rec["id"])["status"] == initial_status


def test_manual_cron_approval_restores_pending_on_cron_lock_timeout(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    rec = store.add_pending(
        category="cron", title="daily", description="", payload={}, origin="test"
    )
    cron_path = config.cron_path()
    before = (cron_path.exists(), cron_path.read_bytes() if cron_path.exists() else b"")
    monkeypatch.setattr(
        cron,
        "add_job",
        lambda **_kwargs: (_ for _ in ()).throw(
            store.FileLockTimeout("cron store is busy; retry.")
        ),
    )

    result = approvals.approve(rec["id"], approved_by="human:test", approved_via="test")

    assert result == {"ok": False, "error": "cron store is busy; retry."}
    assert store.get_pending(rec["id"])["status"] == "pending"
    assert (
        cron_path.exists(),
        cron_path.read_bytes() if cron_path.exists() else b"",
    ) == before


def test_auto_cron_approval_restores_pending_on_cron_lock_timeout(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    cron_path = config.cron_path()
    before = (cron_path.exists(), cron_path.read_bytes() if cron_path.exists() else b"")
    monkeypatch.setattr(
        cron,
        "add_job",
        lambda **_kwargs: (_ for _ in ()).throw(
            store.FileLockTimeout("cron store is busy; retry.")
        ),
    )

    real_execute_action = approvals.execute_action

    def execute_action(
        category: str,
        payload: dict[str, JSONValue],
        cfg: dict[str, JSONValue] | None = None,
        on_event: EventSink | None = None,
    ) -> str:
        return real_execute_action(category, payload, cfg, on_event)

    monkeypatch.setattr(approvals, "execute_action", execute_action)
    result = approvals.propose(
        category="cron",
        title="daily",
        description="",
        payload={},
        cfg={"auto_approve": ["cron"]},
        origin="test",
    )

    assert result["auto"] is True
    assert result["ok"] is False
    assert result["result"] == "cron store is busy; retry."
    assert store.get_pending(result["id"])["status"] == "pending"
    assert (
        cron_path.exists(),
        cron_path.read_bytes() if cron_path.exists() else b"",
    ) == before


def test_cron_approval_restore_timeout_leaves_executing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    rec = store.add_pending(
        category="cron", title="daily", description="", payload={}, origin="test"
    )
    store.resolve_pending(rec["id"], "approving")
    real_file_lock = store.file_lock
    acquisitions = 0

    class _TimeoutLock:
        def __enter__(self):
            raise store.FileLockTimeout("busy")

        def __exit__(self, *_args):
            return None

    def lock(path):
        nonlocal acquisitions
        acquisitions += 1
        return real_file_lock(path) if acquisitions == 1 else _TimeoutLock()

    monkeypatch.setattr(store, "file_lock", lock)
    monkeypatch.setattr(
        cron,
        "add_job",
        lambda **_kwargs: (_ for _ in ()).throw(
            store.FileLockTimeout("cron store is busy; retry.")
        ),
    )

    result = approval_execution.execute_claimed(rec["id"], approvals.execute_action)

    assert result == {"ok": False, "error": "approval store is busy"}
    assert store.get_pending(rec["id"])["status"] == "executing"


def test_cron_approval_restore_does_not_overwrite_changed_state(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    rec = store.add_pending(
        category="cron", title="daily", description="", payload={}, origin="test"
    )
    store.resolve_pending(rec["id"], "approving")
    real_file_lock = store.file_lock
    acquisitions = 0

    class _ChangingLock:
        def __init__(self, path) -> None:
            self._lock = real_file_lock(path)

        def __enter__(self):
            self._lock.__enter__()
            store.resolve_pending(rec["id"], "rejected")
            return self

        def __exit__(self, *args):
            return self._lock.__exit__(*args)

    def lock(path):
        nonlocal acquisitions
        acquisitions += 1
        return real_file_lock(path) if acquisitions == 1 else _ChangingLock(path)

    monkeypatch.setattr(store, "file_lock", lock)
    monkeypatch.setattr(
        cron,
        "add_job",
        lambda **_kwargs: (_ for _ in ()).throw(
            store.FileLockTimeout("cron store is busy; retry.")
        ),
    )

    result = approval_execution.execute_claimed(rec["id"], approvals.execute_action)

    assert result == {"ok": False, "error": "approval store is busy"}
    assert store.get_pending(rec["id"])["status"] == "rejected"
