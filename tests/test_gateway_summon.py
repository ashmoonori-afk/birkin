"""/summon from a gateway chat: roster, privilege gate, and push-back."""

from __future__ import annotations

import threading


def _gateway(tmp_path, monkeypatch, tg_allowed=("42",)):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    cfg = {**config.DEFAULT_CONFIG, "provider": "claude-cli",
           "gateway_prewarm": False,
           "channels": {"telegram": {"allowed_chat_ids": list(tg_allowed)}}}
    config.save_config(cfg)
    from birkin.gateway.core import Gateway
    return Gateway(config.load_config())


def test_summon_lists_and_describes_the_roster(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    listing = gw.handle("telegram", "42", "/summon")
    assert "meeting-scribe" in listing and "사용법" in listing
    assert "회의록 정리 담당" in gw.handle("telegram", "42",
                                       "/summon meeting-scribe")
    assert "찾을 수 없어요" in gw.handle("telegram", "42", "/summon nobody x")


def test_summon_is_privileged(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch, tg_allowed=())
    out = gw.handle("telegram", "99", "/summon researcher 조사해줘")
    assert "restricted" in out.lower()


def test_summon_runs_off_the_lock_and_reports_back_to_this_chat(
        tmp_path, monkeypatch):
    from birkin import scheduler, summon

    gw = _gateway(tmp_path, monkeypatch)
    delivered = {}
    done = threading.Event()
    seen_ctx = {}

    def fake_summon(name, task, ctx, **kwargs):
        seen_ctx["ctx"] = ctx
        return f"{name}: {task} 완료"

    def fake_deliver(name, chat_id, text, *, channel="telegram"):
        delivered.update(name=name, chat_id=chat_id, text=text,
                         channel=channel)
        done.set()
        return "sent"

    monkeypatch.setattr(summon, "summon", fake_summon)
    monkeypatch.setattr(scheduler, "deliver", fake_deliver)

    ack = gw.handle("telegram", "42", "/summon researcher 경쟁사 가격 조사")

    assert "소환했어요" in ack and "보내드릴게요" in ack
    assert done.wait(5)
    assert delivered == {"name": "리서처", "chat_id": "42",
                         "text": "researcher: 경쟁사 가격 조사 완료",
                         "channel": "telegram"}
    ctx = seen_ctx["ctx"]
    # Its own stop signal and budget: the chat's next message cannot cancel it.
    assert ctx.abort is not gw.session.ctx.abort
    assert ctx.tree_budget is not gw.session.ctx.tree_budget
    assert ctx.emit is None and ctx.shell_prompt_cb is None


def test_help_advertises_summon_as_an_admin_command(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    text = gw.handle("telegram", "42", "/help")
    admin = text.split("관리자용", 1)[1]
    assert "/summon" in admin


def test_long_summon_results_say_they_were_shortened(tmp_path, monkeypatch):
    from birkin import scheduler, summon

    gw = _gateway(tmp_path, monkeypatch)
    delivered = {}
    done = threading.Event()
    monkeypatch.setattr(summon, "summon", lambda *a, **k: "가" * 5000)

    def fake_deliver(name, chat_id, text, *, channel="telegram"):
        delivered["text"] = text
        done.set()
        return "sent"

    monkeypatch.setattr(scheduler, "deliver", fake_deliver)
    gw.handle("telegram", "42", "/summon report-writer 주간 보고서")
    assert done.wait(5)
    assert len(delivered["text"]) < 3500
    assert "앞부분만 보냈어요" in delivered["text"]
