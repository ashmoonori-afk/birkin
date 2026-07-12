"""P2-3: /remind schedules a daily prompt reminder to the current chat."""

from __future__ import annotations


def _gateway(tmp_path, monkeypatch, tg_allowed=("42",)):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    cfg = {**config.DEFAULT_CONFIG, "provider": "claude-cli",
           "gateway_prewarm": False,
           "channels": {"telegram": {"allowed_chat_ids": list(tg_allowed)}}}
    config.save_config(cfg)
    from birkin.gateway.core import Gateway
    return Gateway(config.load_config())


def test_remind_creates_daily_prompt_job(tmp_path, monkeypatch):
    from birkin import cron
    gw = _gateway(tmp_path, monkeypatch)
    out = gw.handle("telegram", "42", "/remind 09:00 오늘 일정 요약해줘")
    assert "09:00" in out
    jobs = cron.load_jobs()
    assert len(jobs) == 1
    j = jobs[0]
    assert j["hour"] == 9 and j["minute"] == 0
    assert j["type"] == "prompt"                     # never shell
    assert j["deliver_chat_id"] == "42"              # this chat only
    assert "일정 요약" in j["value"]


def test_remind_list_and_delete(tmp_path, monkeypatch):
    from birkin import cron
    gw = _gateway(tmp_path, monkeypatch)
    gw.handle("telegram", "42", "/remind 8:30 A")
    out = gw.handle("telegram", "42", "/remind list")
    assert "08:30" in out
    jid = cron.load_jobs()[0]["id"]
    out2 = gw.handle("telegram", "42", f"/remind del {jid}")
    assert "삭제" in out2
    assert cron.load_jobs() == []


def test_remind_is_privileged(tmp_path, monkeypatch):
    # open bot (no allowed_chat_ids) may not schedule
    gw = _gateway(tmp_path, monkeypatch, tg_allowed=())
    out = gw.handle("telegram", "99", "/remind 09:00 x")
    assert "restricted" in out.lower()
    from birkin import cron
    assert cron.load_jobs() == []


def test_remind_cannot_delete_another_chats_job(tmp_path, monkeypatch):
    from birkin import cron
    gw = _gateway(tmp_path, monkeypatch, tg_allowed=("42", "43"))
    gw.handle("telegram", "42", "/remind 09:00 mine")
    jid = cron.load_jobs()[0]["id"]
    out = gw.handle("telegram", "43", f"/remind del {jid}")
    assert "찾지 못" in out
    assert len(cron.load_jobs()) == 1                # not deleted


def test_remind_bad_format_is_guided(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    out = gw.handle("telegram", "42", "/remind not a time")
    assert "형식" in out
    from birkin import cron
    assert cron.load_jobs() == []
