from __future__ import annotations

import threading

from birkin import approvals, store
from birkin.gateway import workflow
from birkin.gateway.channels.telegram import TelegramChannel
from birkin.tools import ToolContext, build_registry


def test_claimed_action_executes_only_its_stored_payload(
        tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    rec = store.add_pending(
        category="note",
        title="stored",
        description="",
        payload={"value": "stored"},
        origin="test",
    )
    assert approvals.claim(rec["id"])["ok"] is True
    executed: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        approvals,
        "execute_action",
        lambda category, payload: executed.append((category, payload)) or "done",
    )

    result = approvals.execute_claimed(rec["id"])

    assert result["ok"] is True
    assert executed == [("note", {"value": "stored"})]
    assert store.get_pending(rec["id"])["status"] == "approved"


def test_generic_approval_surfaces_hide_telegram_workflows(
        tmp_path, monkeypatch) -> None:
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
        def claim_action(_aid):
            return "running", True

        @staticmethod
        def execute_claimed_action(_aid):
            started.set()
            release.wait(timeout=2)
            return "done"

    channel = TelegramChannel("token", allowed_chat_ids=["42"])
    monkeypatch.setattr(
        channel, "_call", lambda *_args, **_kwargs: {"ok": True})
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
    release.set()
    channel._action_workers["42"].join(timeout=2)


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


def test_approval_transition_fails_when_lock_is_not_acquired(
        tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    rec = store.add_pending(
        category="note", title="locked", description="", payload={}, origin="test")

    class _UnavailableLock:
        acquired = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(store, "file_lock", lambda _path: _UnavailableLock())

    result = approvals.claim(rec["id"])

    assert result["ok"] is False
    assert "busy" in result["error"]
    assert store.get_pending(rec["id"])["status"] == "pending"
