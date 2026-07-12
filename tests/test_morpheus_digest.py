"""P0-3: the nightly Morpheus pass delivers a morning digest to chat."""

from __future__ import annotations


def _cfg(tmp_path, monkeypatch, chat="42"):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    cfg = {**config.DEFAULT_CONFIG, "morpheus_deliver_chat_id": chat}
    config.save_config(cfg)
    return cfg


def test_digest_delivers_summary_with_pending_count(tmp_path, monkeypatch):
    from birkin import morpheus, scheduler, store
    cfg = _cfg(tmp_path, monkeypatch)
    store.add_pending(category="note", title="queued overnight",
                      description="", payload={}, origin="morpheus")
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(scheduler, "deliver",
                        lambda name, chat, text: sent.append(
                            (name, chat, text)) or "sent")
    morpheus._deliver_digest(cfg, "Learned two things tonight.")
    assert sent and sent[0][0] == "morpheus" and sent[0][1] == "42"
    assert "Learned two things" in sent[0][2]
    assert "1 pending approval" in sent[0][2]      # /pending one tap away
    assert "/pending" in sent[0][2]


def test_digest_off_when_no_chat_configured(tmp_path, monkeypatch):
    from birkin import morpheus, scheduler
    cfg = _cfg(tmp_path, monkeypatch, chat="")
    called: list = []
    monkeypatch.setattr(scheduler, "deliver",
                        lambda *a: called.append(a) or "sent")
    morpheus._deliver_digest(cfg, "summary")
    assert called == []                            # off by default


def test_silent_summary_stays_silent(tmp_path, monkeypatch):
    # [SILENT] must reach scheduler.deliver UNMODIFIED (no pending suffix
    # appended) so its first-token check suppresses the send.
    from birkin import morpheus, scheduler, store
    cfg = _cfg(tmp_path, monkeypatch)
    store.add_pending(category="note", title="x", description="",
                      payload={}, origin="morpheus")
    sent: list[str] = []
    monkeypatch.setattr(scheduler, "deliver",
                        lambda name, chat, text: sent.append(text)
                        or "skipped-silent")
    morpheus._deliver_digest(cfg, "[SILENT] nothing durable happened")
    assert sent and sent[0].startswith("[SILENT]")


def test_scheduler_deliver_wrapper_honors_silent_and_allowlist(tmp_path,
                                                               monkeypatch):
    from birkin import config, scheduler
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    cfg = {**config.DEFAULT_CONFIG,
           "channels": {"telegram": {"allowed_chat_ids": ["42"],
                                     "token": "tok"}}}
    config.save_config(cfg)
    assert scheduler.deliver("m", "", "hi") == "none"
    assert scheduler.deliver("m", "42", "[SILENT] n/a") == "skipped-silent"
    # outbound allowlist: a stranger's chat is refused before any HTTP
    assert scheduler.deliver("m", "666", "hi").startswith("error:")
