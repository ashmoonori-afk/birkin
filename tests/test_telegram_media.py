"""P2-1: inbound media (photo/voice/document) reaches the agent as a turn."""

from __future__ import annotations

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
