"""Tests for auto-save conversation transcripts (birkin/transcripts.py)."""

from __future__ import annotations

import json
import threading

import pytest

from birkin import transcripts


def _fake_secrets() -> dict[str, str]:
    """Secret-shaped (but fake) fixtures built at RUNTIME from split parts, so the
    literal token never appears in this file's source — otherwise GitHub push
    protection blocks the push. They still match transcripts' redaction regexes."""
    return {
        "anthropic": "sk-" + "ant-" + "abc123DEF456ghijklmno",
        "aws": "AKIA" + "ABCDEFGHIJKLMNOP",
        "google": "AIza" + "Sy" + "B" * 35,
        "github": "ghp" + "_" + "b" * 36,
        "slack": "xox" + "b-" + "1234567890-abcdefghijklmno",
        "bearer": "ey" + "JhbGciOiJIUzI1Niabcdef" + "GH",
    }


def test_auto_stem_namespacing():
    stem = transcripts.auto_stem("telegram", "12345", day="20260601")
    assert stem.startswith("auto__telegram__12345-")  # chat + short hash
    assert stem.endswith("__20260601")
    assert transcripts.is_auto(stem) is True
    assert transcripts.is_auto("20260601-120000") is False  # manual /save name
    # distinct chat ids that share a 40-char sanitized prefix don't collide
    a = transcripts.auto_stem("http", "x" * 50 + "A", day="d")
    b = transcripts.auto_stem("http", "x" * 50 + "B", day="d")
    assert a != b


def test_safe_sanitizes_chat_id():
    stem = transcripts.auto_stem("http", "a/b:c d@e", day="20260601")
    body = stem[len(transcripts.AUTO_PREFIX):]
    assert "/" not in body and ":" not in body and " " not in body and "@" not in body


def test_append_turn_writes_morpheus_compatible_format(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import selfimprove
    p = transcripts.append_turn("http", "s1", "hello there", "hi back",
                                cfg={"autosave_transcripts": True})
    assert p is not None and p.exists()
    msgs = json.loads(p.read_text(encoding="utf-8"))
    # canonical shape: list of {role, content:[{type:text,text}]}
    assert msgs == [
        {"role": "user", "content": [{"type": "text", "text": "hello there"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "hi back"}]},
    ]
    # the nightly extractor must be able to flatten it
    flat = selfimprove.transcript_from_messages(msgs)
    assert "[user] hello there" in flat and "[assistant] hi back" in flat


def test_append_turn_accumulates_pairs_one_file(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    cfg = {"autosave_transcripts": True}
    transcripts.append_turn("http", "s1", "q1", "a1", cfg=cfg)
    p = transcripts.append_turn("http", "s1", "q2", "a2", cfg=cfg)
    files = list((tmp_path / "sessions").glob("auto__*.json"))
    assert len(files) == 1                         # same (channel,chat,day) -> one file
    msgs = json.loads(p.read_text(encoding="utf-8"))
    assert [m["content"][0]["text"] for m in msgs] == ["q1", "a1", "q2", "a2"]


def test_opt_out_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    assert transcripts.append_turn("http", "s1", "hi", "yo",
                                   cfg={"autosave_transcripts": False}) is None
    assert not list((tmp_path / "sessions").glob("*.json"))


def test_empty_user_text_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    assert transcripts.append_turn("http", "s1", "   ", "x", cfg={}) is None


def test_never_raises_on_write_error(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setattr(transcripts.store, "_write_json",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    # must swallow and return None, not propagate into the chat path
    assert transcripts.append_turn("http", "s1", "hi", "yo", cfg={}) is None


def test_secret_redaction(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    s = _fake_secrets()
    p = transcripts.append_turn(
        "http", "s1",
        f"my key is {s['anthropic']} ok",
        f"token=supersecretvalue and {s['aws']}",
        cfg={"autosave_transcripts": True, "autosave_redact_secrets": True})
    text = p.read_text(encoding="utf-8")
    assert s["anthropic"] not in text
    assert s["aws"] not in text
    assert "supersecretvalue" not in text
    assert "[redacted]" in text


def test_redaction_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    aws = _fake_secrets()["aws"]
    p = transcripts.append_turn("http", "s1", aws, "ok",
                                cfg={"autosave_redact_secrets": False})
    assert aws in p.read_text(encoding="utf-8")


def test_trim_caps_turns(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    cfg = {"autosave_max_turns": 3}
    p = None
    for i in range(5):
        p = transcripts.append_turn("http", "s1", f"q{i}", f"a{i}", cfg=cfg)
    msgs = json.loads(p.read_text(encoding="utf-8"))
    assert len(msgs) == 6                          # 3 turns * 2 messages
    assert msgs[0]["content"][0]["text"] == "q2"   # oldest turns dropped


def test_retention_deletes_old_auto_keeps_manual(tmp_path, monkeypatch):
    import os
    import time
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    sd = config.sessions_dir()
    old_auto = sd / "auto__http__old__20200101.json"
    old_auto.write_text("[]", encoding="utf-8")
    manual = sd / "mysave.json"
    manual.write_text("[]", encoding="utf-8")
    old = time.time() - 40 * 86400
    os.utime(old_auto, (old, old))
    os.utime(manual, (old, old))
    transcripts._last_retention = 0.0  # bypass throttle
    transcripts._maybe_enforce_retention({"autosave_retention_days": 30})
    assert not old_auto.exists()   # old auto file removed
    assert manual.exists()         # manual save untouched


def test_gather_sessions_includes_auto_files(tmp_path, monkeypatch):
    """The integration that matters: nightly Morpheus picks up auto files."""
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import morpheus
    transcripts.append_turn("telegram", "42", "remember my deadline is friday",
                            "noted", cfg={"autosave_transcripts": True})
    gathered = morpheus._gather_sessions()
    assert "auto__telegram__42" in gathered
    assert "deadline is friday" in gathered


def test_concurrent_appends_same_key_no_corruption(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    cfg = {"autosave_transcripts": True, "autosave_max_turns": 1000}

    def worker(i: int):
        transcripts.append_turn("http", "s1", f"q{i}", f"a{i}", cfg=cfg)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    files = list((tmp_path / "sessions").glob("auto__*.json"))
    assert len(files) == 1
    msgs = json.loads(files[0].read_text(encoding="utf-8"))  # valid JSON, not torn
    assert len(msgs) == 40                                   # 20 turns * 2, none lost


def test_redaction_covers_common_secret_types(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    s = _fake_secrets()
    parts = [s["google"], s["github"], s["slack"],
             "password: my long secret phrase here",            # labeled -> EOL
             "Authorization: Bearer " + s["bearer"]]
    p = transcripts.append_turn("repl", "r1", " ".join(parts), "ok",
                                cfg={"autosave_redact_secrets": True})
    text = p.read_text(encoding="utf-8")
    for leak in (s["google"], s["github"], s["slack"], s["bearer"],
                 "my long secret phrase"):
        assert leak not in text, leak
    assert "[redacted]" in text


def test_max_chars_truncates_long_message(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    p = transcripts.append_turn("repl", "r1", "x" * 9000, "y" * 9000,
                                cfg={"autosave_max_chars": 100})
    msgs = json.loads(p.read_text(encoding="utf-8"))
    assert len(msgs[0]["content"][0]["text"]) < 200  # capped + marker
    assert "truncated" in msgs[0]["content"][0]["text"]


def test_retention_cap_with_tied_mtimes(tmp_path, monkeypatch):
    """Regression: equal mtimes must not raise comparing Path (file-count cap)."""
    import os
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    sd = config.sessions_dir()
    same = 1_700_000_000.0
    for i in range(5):
        f = sd / f"auto__http__c{i}-aaaaaa__20260601.json"
        f.write_text("[]", encoding="utf-8")
        os.utime(f, (same, same))   # identical mtime on purpose
    transcripts._last_retention = 0.0
    transcripts._maybe_enforce_retention({"autosave_max_files": 2,
                                          "autosave_retention_days": 0})
    remaining = list(sd.glob("auto__*.json"))
    assert len(remaining) == 2      # cap enforced, no TypeError swallowed


def test_telegram_autosave_gated_on_allowlist(tmp_path, monkeypatch):
    """Open Telegram bot (no allowed_chat_ids) must NOT persist/memorize turns."""
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    from birkin.gateway.core import Gateway
    # Open bot: telegram enabled, NO allowlist
    config.save_config({**config.DEFAULT_CONFIG, "provider": "claude-cli",
                        "gateway_persistent": False,
                        "channels": {"http": {"enabled": True},
                                     "telegram": {"enabled": True, "token": "x",
                                                  "allowed_chat_ids": []}}})
    gw = Gateway(config.load_config())
    monkeypatch.setattr(gw.session, "ask", lambda text, **k: "reply")
    assert gw._autosave_trusted("telegram") is False
    assert gw._autosave_trusted("repl") is True
    assert gw._autosave_trusted("http") is True
    gw.handle("telegram", "999", "stranger message")
    assert not list((tmp_path / "sessions").glob("auto__telegram__*.json"))


def test_telegram_autosave_allowed_when_allowlisted(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    from birkin.gateway.core import Gateway
    config.save_config({**config.DEFAULT_CONFIG, "provider": "claude-cli",
                        "gateway_persistent": False,
                        "channels": {"http": {"enabled": True},
                                     "telegram": {"enabled": True, "token": "x",
                                                  "allowed_chat_ids": ["777"]}}})
    gw = Gateway(config.load_config())
    monkeypatch.setattr(gw.session, "ask", lambda text, **k: "reply")
    assert gw._autosave_trusted("telegram") is True
    gw.handle("telegram", "777", "trusted message")
    assert list((tmp_path / "sessions").glob("auto__telegram__*.json"))


def test_gateway_handle_autosaves_turn(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    config.save_config({**config.DEFAULT_CONFIG, "provider": "claude-cli",
                        "gateway_persistent": False})
    from birkin.gateway.core import Gateway
    gw = Gateway(config.load_config())
    monkeypatch.setattr(gw.session, "ask", lambda text, **k: "the reply")
    out = gw.handle("http", "c1", "remember X")
    assert out == "the reply"
    files = list((tmp_path / "sessions").glob("auto__http__c1-*.json"))
    assert len(files) == 1
    msgs = json.loads(files[0].read_text(encoding="utf-8"))
    assert msgs[0]["content"][0]["text"] == "remember X"
    assert msgs[1]["content"][0]["text"] == "the reply"


def test_gateway_command_turns_not_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    config.save_config({**config.DEFAULT_CONFIG, "provider": "claude-cli",
                        "gateway_persistent": False})
    from birkin.gateway.core import Gateway
    gw = Gateway(config.load_config())
    gw.handle("http", "c1", "/help")            # a command, not a turn
    assert not list((tmp_path / "sessions").glob("auto__*.json"))


def test_sessions_command_hides_auto(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config, slashcommands
    sd = config.sessions_dir()
    (sd / "manual1.json").write_text("[]", encoding="utf-8")
    (sd / "auto__http__c__20260601.json").write_text("[]", encoding="utf-8")
    slashcommands._sessions(None, "")
    out = capsys.readouterr().out
    assert "manual1" in out and "auto__" not in out


def test_save_rejects_reserved_auto_name(tmp_path, monkeypatch, capsys):
    import types
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import slashcommands
    sess = types.SimpleNamespace(agent=types.SimpleNamespace(messages=[]))
    slashcommands._save(sess, "auto__sneaky")
    assert "reserved" in capsys.readouterr().out.lower()
    assert not (tmp_path / "sessions" / "auto__sneaky.json").exists()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
