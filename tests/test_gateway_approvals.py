"""P0-2: the propose->approve loop completes from chat (inline buttons)."""

from __future__ import annotations

import json
from pathlib import Path


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
    gw2 = _gateway(tmp_path, monkeypatch, tg_allowed=())
    assert "restricted" in gw2.handle("telegram", "99", "/pending").lower()


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
    # double-resolve is safe
    assert "⚠" in gw.resolve_action(
        a["id"],
        approve=True,
        actor_id="human:telegram:42",
        via="gateway:telegram",
    )


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


def test_approval_markup_shape():
    from birkin.gateway.channels.telegram import TelegramChannel
    kb = json.loads(TelegramChannel._approval_markup("abc-123"))
    row = kb["inline_keyboard"][0]
    assert row[0]["callback_data"] == "apv:abc-123"
    assert row[1]["callback_data"] == "rej:abc-123"
    # 64-byte Telegram limit respected even for absurd ids
    kb2 = json.loads(TelegramChannel._approval_markup("x" * 200))
    assert len(kb2["inline_keyboard"][0][0]["callback_data"]) <= 64
