"""Regression tests for three gateway bugs fixed together.

1. Restart amnesia: transcripts.append_turn wrote history to disk but nothing
   ever read it back — a restarted gateway forgot every conversation. Now
   transcripts.read_recent reads the tail and Gateway.handle seeds the first
   turn per conversation key with it (/new opts out).
2. Attachment drops: TelegramChannel._extract_attachments rooted only at
   Path.cwd(), but the codex session writes into config workspace_roots —
   every file the agent produced resolved outside the root and was dropped.
3. Silent heartbeats on approved work: _PolishingGateway.handle did not
   declare on_progress, so telegram._run_turn's signature check silently
   dropped the callback and the chat heartbeat showed a bare minute counter
   while the work stage appeared only in the server log.
"""

from __future__ import annotations

import inspect
import types

from birkin import transcripts
from birkin.gateway import core as gw_core
from birkin.gateway.channels import telegram as tg
from birkin.gateway.channels.polished_telegram import _PolishingGateway


# ---------------- 3. polished gateway forwards on_progress ----------------

class _RecordingGateway:
    """Bare gateway double: records the on_progress it was handed."""

    pending_hard_restart = False

    def __init__(self) -> None:
        self.seen_progress: object = "NOT PASSED"

    def handle(self, channel, chat_id, text, on_text=None, workflow_id=None,
               on_progress=None):
        self.seen_progress = on_progress
        return "done"


def test_polishing_gateway_forwards_on_progress():
    inner = _RecordingGateway()
    wrapper = _PolishingGateway(inner, {})  # empty cfg -> polish is a no-op
    cb = lambda info: None  # noqa: E731
    reply = wrapper.handle("telegram", "42", "hi", on_progress=cb)
    assert reply == "done"
    assert inner.seen_progress is cb


def test_polishing_gateway_signature_passes_the_channel_check():
    """telegram._run_turn inspects handle()'s parameters; the wrapper must
    declare on_progress or the callback is silently dropped for exactly the
    long approved-work turns."""
    params = inspect.signature(_PolishingGateway.handle).parameters
    assert "on_progress" in params


# ---------------- 2. attachments resolve from workspace_roots ----------------

def test_attachment_resolves_from_workspace_root(monkeypatch, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    artifact = ws / "report.html"
    artifact.write_text("<!doctype html>", encoding="utf-8")
    gateway_cwd = tmp_path / "gateway-cwd"
    gateway_cwd.mkdir()
    monkeypatch.chdir(gateway_cwd)  # gateway cwd != workspace root
    monkeypatch.setattr(tg.config, "load_config",
                        lambda: {"workspace_roots": [str(ws)]})
    visible, paths = tg.TelegramChannel._extract_attachments(
        '완성했습니다.\n<telegram-attachment path="report.html" />')
    assert visible == "완성했습니다."
    assert paths == [artifact.resolve()]


def test_absolute_attachment_inside_workspace_root(monkeypatch, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    artifact = ws / "out.pdf"
    artifact.write_bytes(b"%PDF")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tg.config, "load_config",
                        lambda: {"workspace_roots": [str(ws)]})
    _visible, paths = tg.TelegramChannel._extract_attachments(
        f'<telegram-attachment path="{artifact}" />')
    assert paths == [artifact.resolve()]


def test_attachment_outside_all_roots_is_still_rejected(monkeypatch, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    monkeypatch.chdir(ws)
    monkeypatch.setattr(tg.config, "load_config",
                        lambda: {"workspace_roots": [str(ws)]})
    _visible, paths = tg.TelegramChannel._extract_attachments(
        f'<telegram-attachment path="{outside}" />')
    assert paths == []


# ---------------- 1. restart history seed ----------------

def test_read_recent_round_trips_append_turn():
    transcripts.append_turn("telegram", "42", "내 이름은 제인이야",
                            "반가워요 제인님", cfg={})
    tail = transcripts.read_recent("telegram", "42")
    assert "내 이름은 제인이야" in tail
    assert "반가워요 제인님" in tail


def test_read_recent_missing_history_is_empty():
    assert transcripts.read_recent("telegram", "no-such-chat") == ""


def _fake_session(reply_prefix="echo:"):
    agent = types.SimpleNamespace(messages=[])

    def ask(text, on_text=None, **_kwargs):
        agent.messages.append({"role": "user", "content": [
            {"type": "text", "text": text}]})
        return f"{reply_prefix}{text}"

    return types.SimpleNamespace(cfg={}, agent=agent, ask=ask)


def test_gateway_seeds_first_turn_with_saved_history(monkeypatch):
    # A previous process saved this conversation.
    transcripts.append_turn("http", "u1", "이전 질문", "이전 답변", cfg={})
    fake = _fake_session()
    monkeypatch.setattr(gw_core, "build_session", lambda cfg: fake)
    g = gw_core.Gateway({})

    g.handle("http", "u1", "새 메시지")
    first_sent = fake.agent.messages[0]["content"][0]["text"]
    assert "이전 질문" in first_sent
    assert "이전 답변" in first_sent
    assert "새 메시지" in first_sent

    # Second turn on the same key is NOT re-seeded.
    g.handle("http", "u1", "둘째 메시지")
    second_sent = fake.agent.messages[-1]["content"][0]["text"]
    assert "이전 질문" not in second_sent


def test_slash_new_opts_out_of_seeding(monkeypatch):
    transcripts.append_turn("http", "u1", "이전 질문", "이전 답변", cfg={})
    fake = _fake_session()
    monkeypatch.setattr(gw_core, "build_session", lambda cfg: fake)
    g = gw_core.Gateway({})

    g.handle("http", "u1", "/new")
    g.handle("http", "u1", "완전히 새로")
    sent = fake.agent.messages[0]["content"][0]["text"]
    assert "이전 질문" not in sent
    assert "이전 대화 기록" not in sent
