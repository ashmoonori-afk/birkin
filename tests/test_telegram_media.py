"""P2-1: inbound media (photo/voice/document) reaches the agent as a turn."""

from __future__ import annotations

import re

from birkin.gateway import core
from birkin.gateway.channels import telegram
from birkin.gateway.channels.telegram import TelegramChannel


def _ch(monkeypatch, tmp_path, downloaded="ok"):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    ch = TelegramChannel("tok", allowed_chat_ids=["42"])
    monkeypatch.setattr(ch, "_download_media",
                        lambda fid: str(tmp_path / "uploads" / "f.jpg")
                        if downloaded else None)
    return ch


def test_incoming_media_prefers_largest_photo():
    ch = TelegramChannel("t")
    msg = {"photo": [{"file_id": "s", "file_size": 100},
                     {"file_id": "L", "file_size": 9000}]}
    assert ch._incoming_media(msg) == ("L", 9000)


def test_incoming_media_document_and_none():
    ch = TelegramChannel("t")
    assert ch._incoming_media(
        {"document": {"file_id": "d", "file_size": 5}}) == ("d", 5)
    assert ch._incoming_media({"text": "hi"}) is None


def test_photo_becomes_a_path_turn_with_caption(monkeypatch, tmp_path):
    ch = _ch(monkeypatch, tmp_path)
    msg = {"photo": [{"file_id": "L", "file_size": 9000}],
           "caption": "이 영수증 정리해줘"}
    out = ch._compose_media_text(msg)
    assert "이 영수증 정리해줘" in out
    assert "파일을 보냈습니다" in out and "f.jpg" in out    # local path handed off


def test_voice_notes_stt_is_unset(monkeypatch, tmp_path):
    ch = _ch(monkeypatch, tmp_path)
    out = ch._compose_media_text({"voice": {"file_id": "v", "file_size": 1000}})
    assert "음성" in out and "STT" in out                 # honest: not transcribed


def test_oversized_file_is_refused_without_download(monkeypatch, tmp_path):
    ch = _ch(monkeypatch, tmp_path, downloaded=None)
    called = {"n": 0}
    monkeypatch.setattr(ch, "_download_media",
                        lambda fid: called.__setitem__("n", 1))
    out = ch._compose_media_text(
        {"document": {"file_id": "big", "file_size": 25_000_000}})
    assert "20MB" in out
    assert called["n"] == 0                                # never downloaded


def test_failed_download_degrades_to_note(monkeypatch, tmp_path):
    ch = _ch(monkeypatch, tmp_path, downloaded=None)
    out = ch._compose_media_text(
        {"document": {"file_id": "d", "file_size": 10}})
    assert "받지 못했" in out


def test_download_media_sanitizes_and_caps(monkeypatch, tmp_path):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    ch = TelegramChannel("tok")
    monkeypatch.setattr(ch, "_call",
                        lambda m, p, timeout=60: {"ok": True,
                                                  "result": {"file_path":
                                                             "../../etc/passwd"}})
    import urllib.request

    class _R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n): return b"IMGDATA"
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=60: _R())
    path = ch._download_media("abcdef123456")
    assert path is not None
    assert "etc" not in path and "passwd" in path         # basename only
    assert (tmp_path / "uploads").exists()


def test_outbound_attachment_marker_sends_file_without_leaking_marker(
        monkeypatch, tmp_path):
    artifact = tmp_path / "market-terminal.html"
    artifact.write_text("<!doctype html><title>Market</title>",
                        encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    ch = TelegramChannel("tok")
    messages: list[tuple[str, str]] = []
    documents: list[tuple[str, object]] = []
    monkeypatch.setattr(
        ch, "_send_reply",
        lambda chat_id, text: messages.append((chat_id, text)))
    monkeypatch.setattr(
        ch, "_send_document",
        lambda chat_id, path: documents.append((chat_id, path)) or True)

    ch._deliver_reply(
        "42",
        '완성했습니다.\n<telegram-attachment path="market-terminal.html" />',
    )

    assert messages == [("42", "완성했습니다.")]
    assert documents == [("42", artifact.resolve())]


def test_send_document_posts_multipart_file(monkeypatch, tmp_path):
    artifact = tmp_path / "market-terminal.html"
    artifact.write_text("<!doctype html><title>Market</title>",
                        encoding="utf-8")
    ch = TelegramChannel("tok")
    captured = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read():
            return b'{"ok": true}'

    def fake_open(request, timeout=60):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_open)

    assert ch._send_document("42", artifact)
    request = captured["request"]
    assert request.full_url.endswith("/bottok/sendDocument")
    assert "multipart/form-data" in request.get_header("Content-type")
    assert b'name="chat_id"' in request.data
    assert b'name="document"' in request.data
    assert b"market-terminal.html" in request.data
    assert artifact.read_bytes() in request.data


def test_gateway_policy_declares_parseable_attachment_marker():
    match = re.search(
        r'<telegram-attachment path="([^"]+)" />',
        core._TELEGRAM_EXECUTION_POLICY,
    )
    assert match is not None
    assert match.group(1).endswith(".ext")


def test_oversized_document_is_rejected_before_reading(
        monkeypatch, tmp_path):
    artifact = tmp_path / "oversized.html"
    with artifact.open("wb") as handle:
        handle.truncate(telegram._MAX_DOCUMENT_BYTES + 1)
    read_attempted = False

    def track_read(_path):
        nonlocal read_attempted
        read_attempted = True
        return b""

    monkeypatch.setattr(type(artifact), "read_bytes", track_read)

    assert not TelegramChannel("tok")._send_document("42", artifact)
    assert not read_attempted


def test_attachment_only_stream_never_exposes_internal_marker():
    sent: list[str] = []
    streamer = telegram._Streamer(
        lambda text: sent.append(text) or "1",
        lambda _message_id, _text: True,
        interval=0,
        min_first=1,
        min_delta=1,
    )

    streamer.feed(
        '<telegram-attachment path="market-terminal.html" />')

    assert sent == []


def test_outbound_attachment_cannot_escape_workspace(monkeypatch, tmp_path):
    outside = tmp_path / "secret.html"
    outside.write_text("private", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    ch = TelegramChannel("tok")
    messages: list[str] = []
    documents: list[object] = []
    monkeypatch.setattr(
        ch, "_send_reply",
        lambda _chat_id, text: messages.append(text))
    monkeypatch.setattr(
        ch, "_send_document",
        lambda _chat_id, path: documents.append(path) or True)

    ch._deliver_reply(
        "42",
        '완성했습니다.\n<telegram-attachment path="../secret.html" />',
    )

    assert messages == ["완성했습니다."]
    assert documents == []
