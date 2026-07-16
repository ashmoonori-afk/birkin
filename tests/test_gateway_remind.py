"""P2-3: /remind schedules a daily prompt reminder to the current chat."""

from __future__ import annotations

import pytest


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


@pytest.mark.parametrize("operation", ["add", "delete"])
def test_remind_add_and_delete_report_busy_without_mutating_on_lock_timeout(
        tmp_path, monkeypatch, operation):
    from birkin import config, cron, store

    gw = _gateway(tmp_path, monkeypatch)
    if operation == "delete":
        job = cron.add_job(
            name="remind", hour=9, minute=0, action_type="prompt",
            value="keep", deliver_chat_id="42")
        command = f"/remind del {job['id']}"
    else:
        command = "/remind 09:00 keep"
    path = config.cron_path()
    existed_before = path.exists()
    bytes_before = path.read_bytes() if existed_before else None

    class _TimeoutLock:
        def __enter__(self):
            raise store.FileLockTimeout("cron store is busy; retry.")

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    monkeypatch.setattr(store, "file_lock", lambda _path: _TimeoutLock())

    assert gw.handle("telegram", "42", command) == (
        "⚠ 리마인더 저장소가 사용 중입니다. 잠시 후 다시 시도해 주세요.")
    assert path.exists() is existed_before
    if existed_before:
        assert path.read_bytes() == bytes_before
