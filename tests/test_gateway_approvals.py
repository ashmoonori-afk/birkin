"""P0-2: the propose->approve loop completes from chat (inline buttons)."""

from __future__ import annotations

import json
from pathlib import Path

from birkin import approval_text
from birkin.gateway.turn_admission import PRIVILEGED_COMMAND_REPLY


def _gateway(tmp_path, monkeypatch, tg_allowed=("42",)):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    cfg = {**config.DEFAULT_CONFIG, "provider": "claude-cli",
           "gateway_prewarm": False,
           "checkpoints": False,
           "channels": {"telegram": {"allowed_chat_ids": list(tg_allowed)}}}
    config.save_config(cfg)
    from birkin.gateway.core import Gateway
    return Gateway(config.load_config())


def _queue_pending(title="test action"):
    from birkin import store
    return store.add_pending(category="memory", title=title,
                             description="a harmless queued action",
                             payload={}, origin="test")


def test_pending_command_lists_and_is_privileged(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    rec = _queue_pending()
    out = gw.handle("telegram", "42", "/pending")
    assert rec["id"] in out and "test action" in out
    # untrusted channel (open bot) is refused
    assert "[memory]" not in out
    gw2 = _gateway(tmp_path, monkeypatch, tg_allowed=())
    assert gw2.handle("telegram", "99", "/pending") == PRIVILEGED_COMMAND_REPLY


def test_resolve_action_roundtrip(tmp_path, monkeypatch):
    from birkin import store
    gw = _gateway(tmp_path, monkeypatch)
    a = _queue_pending("approve me")
    b = _queue_pending("reject me")
    out_a = gw.resolve_action(
        a["id"],
        approve=True,
        actor_id="human:telegram:42",
        via="gateway:telegram",
    )
    assert out_a.startswith("✅")
    out_b = gw.resolve_action(
        b["id"],
        approve=False,
        actor_id="human:telegram:42",
        via="gateway:telegram",
    )
    assert out_b.startswith("❌")
    assert store.list_pending() == []          # both resolved
    # double-resolve is safe, and says the record was already approved
    again = gw.resolve_action(
        a["id"],
        approve=True,
        actor_id="human:telegram:42",
        via="gateway:telegram",
    )
    assert again == approval_text.resolved_elsewhere(store.get_pending(a["id"])).render()
    assert "✅" not in again


def test_gateway_approves_sealed_native_operation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from birkin import store
    from birkin.tools import ToolContext, build_registry

    # Given: a native file-policy block is visible to the gateway approval UI.
    gateway = _gateway(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path.parent / f"{tmp_path.name}-approved.txt"
    queued = build_registry(ToolContext(
        cfg={"fs_jail": True},
        client=None,
        cwd=workspace,
    ), include={"files"}).execute(
        "write_file",
        {"path": str(target), "content": "gateway approved"},
    )
    approval_id = store.list_pending()[0]["id"]

    # When: the authorized gateway principal approves the exact operation.
    result = gateway.resolve_action(
        approval_id,
        approve=True,
        actor_id="human:telegram:42",
        via="gateway:telegram",
    )

    # Then: the sealed action executes once through the same approval worker.
    assert "queued for approval" in queued.content
    assert result.startswith("✅")
    assert target.read_text(encoding="utf-8") == "gateway approved"
    resolved = store.get_pending(approval_id)
    assert resolved is not None
    assert resolved["status"] == "approved"
    assert resolved["approved_by"] == "human:telegram:42"
    assert resolved["approved_via"] == "gateway:telegram"


def test_callback_tap_approves_and_acks(tmp_path, monkeypatch):
    from birkin.gateway.channels.telegram import TelegramChannel
    gw = _gateway(tmp_path, monkeypatch)
    rec = _queue_pending("button me")
    ch = TelegramChannel("tok", allowed_chat_ids=["42"])
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(ch, "_call",
                        lambda m, p, timeout=60: calls.append((m, p)) or {"ok": True})
    cq = {"id": "cb1", "data": f"apv:{rec['id']}", "from": {"id": 42},
          "message": {"chat": {"id": 42}, "message_id": 7,
                      "text": "[note] button me"}}
    ch._handle_callback(gw, cq)
    methods = [m for m, _ in calls]
    assert "answerCallbackQuery" in methods     # mandatory ACK
    assert "editMessageText" in methods         # in-place outcome
    from birkin import store
    assert store.list_pending() == []           # actually approved


def test_callback_from_unauthorized_chat_is_refused(tmp_path, monkeypatch):
    from birkin.gateway.channels.telegram import TelegramChannel
    gw = _gateway(tmp_path, monkeypatch)
    rec = _queue_pending("locked")
    ch = TelegramChannel("tok", allowed_chat_ids=["42"])
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(ch, "_call",
                        lambda m, p, timeout=60: calls.append((m, p)) or {"ok": True})
    ch._handle_callback(gw, {"id": "cb2", "data": f"apv:{rec['id']}",
                             "message": {"chat": {"id": 666},
                                         "message_id": 9, "text": "x"}})
    from birkin import store
    assert len(store.list_pending()) == 1       # NOT approved
    assert [m for m, _ in calls] == ["answerCallbackQuery"]


def test_open_bot_cannot_tap_approve(tmp_path, monkeypatch):
    from birkin.gateway.channels.telegram import TelegramChannel
    gw = _gateway(tmp_path, monkeypatch, tg_allowed=())
    rec = _queue_pending("open bot")
    ch = TelegramChannel("tok", allowed_chat_ids=[])
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(ch, "_call",
                        lambda m, p, timeout=60: calls.append((m, p)) or {"ok": True})
    ch._handle_callback(gw, {"id": "cb3", "data": f"apv:{rec['id']}",
                             "message": {"chat": {"id": 5},
                                         "message_id": 1, "text": "x"}})
    from birkin import store
    assert len(store.list_pending()) == 1       # open bot may not approve
    toast = next(p for m, p in calls if m == "answerCallbackQuery")["text"]
    assert "allowed_chat_ids" in toast


def test_approval_markup_shape():
    from birkin.gateway.channels.telegram import TelegramChannel
    kb = json.loads(TelegramChannel._approval_markup("abc-123"))
    row = kb["inline_keyboard"][0]
    assert row[0]["callback_data"] == "apv:abc-123"
    assert row[1]["callback_data"] == "rej:abc-123"
    # 64-byte Telegram limit respected even for absurd ids
    kb2 = json.loads(TelegramChannel._approval_markup("x" * 200))
    assert len(kb2["inline_keyboard"][0][0]["callback_data"]) <= 64


def _queue_workflow():
    from birkin import store
    return store.add_pending(category="moirai", title="보고서 작성",
                             description="hard task",
                             payload={"script": "hard-task", "task": "보고서"},
                             origin="test")


def _complete_report(body: str) -> str:
    # The status line moirai.outcome.render puts first; only a complete run
    # reads as a success.
    return f"✅ 워크플로우 완료 (hard-task)\n\n{body}"


def test_approved_result_is_not_cut_at_500_chars(tmp_path, monkeypatch):
    """A workflow report is the receipt; a silent cut at 500 hid the answer."""
    from birkin import approvals
    gw = _gateway(tmp_path, monkeypatch)
    rec = _queue_workflow()
    monkeypatch.setattr(
        approvals, "approve",
        lambda aid, **_kw: {"ok": True, "result": _complete_report("가" * 1500)})

    out = gw.resolve_action(rec["id"], approve=True,
                            actor_id="human:telegram:42",
                            via="gateway:telegram")

    assert out.startswith("✅")
    assert "가" * 1500 in out


def test_an_over_long_approved_result_says_it_was_cut(tmp_path, monkeypatch):
    from birkin import approvals
    gw = _gateway(tmp_path, monkeypatch)
    rec = _queue_workflow()
    monkeypatch.setattr(
        approvals, "execute_claimed",
        lambda aid, on_event=None: {"ok": True,
                                   "result": _complete_report("가" * 5000)})

    out = gw.execute_claimed_action(rec["id"])

    assert out.startswith("✅")
    assert "결과가 길어" in out
    assert len(out) <= 3300


def test_claimed_action_reply_is_korean(tmp_path, monkeypatch):
    from birkin import approvals
    gw = _gateway(tmp_path, monkeypatch)
    monkeypatch.setattr(approvals, "claim", lambda aid, **_kw: {"ok": True})

    assert gw.claim_action("abc123abc123", actor_id="human:telegram:42",
                           via="gateway:telegram") == (
        f"⏳ {approval_text.CLAIMED}", True)


def test_moirai_approval_card_shows_the_workflow_and_task():
    from birkin.gateway.channels.telegram import _payload_summary
    summary = _payload_summary(
        "moirai", {"script": "hard-task", "task": "주간 보고서 이어서"})
    assert "hard-task" in summary
    assert "주간 보고서 이어서" in summary
    assert summary.startswith("↳ 워크플로우:")
