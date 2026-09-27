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

    result = approval_execution.approve(
        rec["id"],
        approvals.execute_action,
        approved_by="human:test",
        approved_via="test",
    )

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


def _approval_gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    cfg = {**config.DEFAULT_CONFIG, "provider": "claude-cli",
           "gateway_prewarm": False, "checkpoints": False,
           "channels": {"telegram": {"allowed_chat_ids": ["42"]}}}
    config.save_config(cfg)
    from birkin.gateway.core import Gateway
    return Gateway(config.load_config())


def test_a_failed_shell_approval_is_never_reported_with_a_check_mark(
    tmp_path, monkeypatch
) -> None:
    gw = _approval_gateway(tmp_path, monkeypatch)
    rec = store.add_pending(category="shell", title="fails", description="",
                            payload={"command": "exit 3", "cwd": str(tmp_path)},
                            origin="test")

    claimed, ok = gw.claim_action(rec["id"], actor_id="human:telegram:42",
                                  via="gateway:telegram")
    final = gw.execute_claimed_action(rec["id"])

    assert ok is True and claimed.startswith("⏳")
    assert final.startswith("⚠")
    assert "종료 코드 3" in final
    assert "approved" not in final


def test_an_integrity_failure_is_logged_not_shown_raw(
    tmp_path, monkeypatch, capsys
) -> None:
    gw = _approval_gateway(tmp_path, monkeypatch)
    monkeypatch.setattr(
        approvals, "execute_claimed",
        lambda aid, on_event=None: {
            "ok": False,
            "error": "approval execution could not be armed: /secret/path",
        },
    )

    reply = gw.execute_claimed_action("abcdef012345")

    assert "/secret/path" not in reply
    assert "could not be armed" not in reply
    assert "E_APPROVAL_INTEGRITY" in capsys.readouterr().out


def test_an_office_receipt_reads_as_destination_not_json(
    tmp_path, monkeypatch
) -> None:
    import json

    gw = _approval_gateway(tmp_path, monkeypatch)
    rec = store.add_pending(category="office_job", title="report", description="",
                            payload={"job_id": "job-1"}, origin="test")
    receipt = json.dumps({
        "publication": {"artifact": {"artifact_id": "art-1"}},
        "export": {
            "path": "/home/u/out/report.docx",
            "issued_at": "2026-09-26T00:00:00+00:00",
            "expires_at": "2026-10-26T00:00:00+00:00",
        },
        "validation": {"valid": True, "layers": {"fidelity": {"status": "pass"}}},
    })
    monkeypatch.setattr(
        approvals, "execute_claimed",
        lambda aid, on_event=None: {"ok": True, "result": receipt},
    )

    reply = gw.execute_claimed_action(rec["id"])

    assert "{" not in reply
    assert "/home/u/out/report.docx" in reply
    assert "구조 검증" in reply


def test_pending_text_uses_korean_labels_and_marks_questions(
    tmp_path, monkeypatch
) -> None:
    from birkin import approval_text

    gw = _approval_gateway(tmp_path, monkeypatch)
    store.add_pending(category="cron", title="daily", description="",
                      payload={"value": "hi"}, origin="test")
    store.add_pending(category="question", title="Q", description="which?",
                      payload={}, origin="test")

    text = gw.pending_text()

    assert "[cron]" not in text
    assert approval_text.category_label("cron") in text
    assert " · 답변 필요" in text


def test_a_tap_on_a_record_approved_in_the_terminal_says_so(
    tmp_path, monkeypatch
) -> None:
    gw = _approval_gateway(tmp_path, monkeypatch)
    rec = store.add_pending(category="memory", title="note", description="",
                            payload={}, origin="test")
    monkeypatch.setattr(approvals, "execute_action",
                        lambda category, payload, cfg=None, on_event=None: "saved")
    assert approvals.approve(rec["id"], approved_by="human:terminal",
                             approved_via="terminal:review")["ok"] is True

    reply = gw.resolve_action(rec["id"], approve=True,
                              actor_id="human:telegram:42", via="gateway:telegram")

    assert "터미널에서 이미 승인" in reply
