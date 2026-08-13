from __future__ import annotations

import types

from birkin.gateway import core as gw_core


def _fake_session():
    agent = types.SimpleNamespace(messages=[])

    def ask(text, on_text=None, **_kwargs):
        agent.messages.append({
            "role": "user",
            "content": [{"type": "text", "text": text}],
        })
        return "ok"

    return types.SimpleNamespace(cfg={}, agent=agent, ask=ask)


def _trusted_telegram_config(chat_id: str = "42") -> dict:
    return {
        "autosave_transcripts": True,
        "channels": {
            "telegram": {
                "allowed_chat_ids": [chat_id],
            },
        },
    }


def test_short_followup_targets_previous_substantive_user_request(
        monkeypatch, tmp_path):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    fake = _fake_session()
    monkeypatch.setattr(gw_core, "build_session", lambda cfg: fake)
    gateway = gw_core.Gateway(_trusted_telegram_config())

    gateway.handle(
        "telegram",
        "42",
        "npm i -g omo-ai@beta가 EBUSY로 실패했어. 왜 뜨는 거야?",
    )
    gateway.handle("telegram", "42", "쉽게 설명해")

    sent = fake.agent.messages[-1]["content"][0]["text"]
    assert "<conversation-followup-context>" in sent
    assert "EBUSY로 실패했어" in sent
    assert sent.endswith("쉽게 설명해")


def test_followup_anchor_is_isolated_per_chat(monkeypatch, tmp_path):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    fake = _fake_session()
    monkeypatch.setattr(gw_core, "build_session", lambda cfg: fake)
    cfg = _trusted_telegram_config(chat_id="42")
    cfg["channels"]["telegram"]["allowed_chat_ids"].append("99")
    gateway = gw_core.Gateway(cfg)

    gateway.handle("telegram", "42", "npm 설치가 EBUSY로 실패했어")
    gateway.handle("telegram", "99", "파이썬 데코레이터가 뭐야?")

    gateway.handle("telegram", "42", "쉽게 설명해")
    chat_42_prompt = fake.agent.messages[-1]["content"][0]["text"]
    gateway.handle("telegram", "99", "쉽게 설명해")
    chat_99_prompt = fake.agent.messages[-1]["content"][0]["text"]

    assert "EBUSY로 실패했어" in chat_42_prompt
    assert "데코레이터가 뭐야?" not in chat_42_prompt
    assert "데코레이터가 뭐야?" in chat_99_prompt
    assert "EBUSY로 실패했어" not in chat_99_prompt


def test_explicit_new_topic_is_not_rewritten(monkeypatch, tmp_path):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    fake = _fake_session()
    monkeypatch.setattr(gw_core, "build_session", lambda cfg: fake)
    gateway = gw_core.Gateway(_trusted_telegram_config())

    gateway.handle("telegram", "42", "npm 설치가 EBUSY로 실패했어")
    new_topic = "파이썬 데코레이터를 쉽게 설명해"
    gateway.handle("telegram", "42", new_topic)

    sent = fake.agent.messages[-1]["content"][0]["text"]
    assert "<conversation-followup-context>" not in sent
    assert sent.endswith(new_topic)


def test_short_followup_uses_restored_substantive_request_after_restart(
        monkeypatch, tmp_path):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    sessions = iter((_fake_session(), _fake_session()))
    monkeypatch.setattr(gw_core, "build_session", lambda cfg: next(sessions))
    cfg = _trusted_telegram_config()

    first_gateway = gw_core.Gateway(cfg)
    first_gateway.handle(
        "telegram",
        "42",
        "npm i -g omo-ai@beta가 EBUSY로 실패했어. 왜 뜨는 거야?",
    )

    restarted_gateway = gw_core.Gateway(cfg)
    restarted_gateway.handle("telegram", "42", "쉽게 설명해")

    sent = restarted_gateway.session.agent.messages[-1]["content"][0]["text"]
    assert "<conversation-followup-context>" in sent
    assert "EBUSY로 실패했어" in sent
    assert sent.endswith("쉽게 설명해")


def test_slash_new_clears_followup_anchor(monkeypatch, tmp_path):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    fake = _fake_session()
    monkeypatch.setattr(gw_core, "build_session", lambda cfg: fake)
    gateway = gw_core.Gateway(_trusted_telegram_config())

    gateway.handle("telegram", "42", "npm 설치가 EBUSY로 실패했어")
    assert gateway.handle("telegram", "42", "/new") == (
        "Started a new conversation."
    )
    gateway.handle("telegram", "42", "쉽게 설명해")

    sent = fake.agent.messages[-1]["content"][0]["text"]
    assert "<conversation-followup-context>" not in sent
    assert "EBUSY로 실패했어" not in sent


def test_restart_skips_saved_followups_to_find_substantive_request(
        monkeypatch, tmp_path):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    sessions = iter((_fake_session(), _fake_session()))
    monkeypatch.setattr(gw_core, "build_session", lambda cfg: next(sessions))
    cfg = _trusted_telegram_config()

    first_gateway = gw_core.Gateway(cfg)
    first_gateway.handle("telegram", "42", "npm 설치가 EBUSY로 실패했어")
    first_gateway.handle("telegram", "42", "쉽게 설명해")

    restarted_gateway = gw_core.Gateway(cfg)
    restarted_gateway.handle("telegram", "42", "자세히 설명해")

    sent = restarted_gateway.session.agent.messages[-1]["content"][0]["text"]
    assert (
        "<previous-user-request>\n"
        "npm 설치가 EBUSY로 실패했어\n"
        "</previous-user-request>"
    ) in sent
    assert (
        "<previous-user-request>\n"
        "쉽게 설명해\n"
        "</previous-user-request>"
    ) not in sent
