"""Cynefin classifier and promptgate hook (design item 1)."""

from __future__ import annotations

import pytest

from birkin import config, cynefin, promptgate

CASES = [
    # clear: short questions and explain-asks
    ("what does the ledger module do?", "clear"),
    ("How are you?", "clear"),
    ("", "clear"),
    ("이 함수 설명해줘", "clear"),
    # complicated: single-goal commands
    ("fix the typo in README.md", "complicated"),
    ("add a --json flag to the status command", "complicated"),
    # complex: multi-goal build requests (English and Korean)
    ("implement the exporter and then add tests, also update the docs",
     "complex"),
    ("로그인 만들어 주고 그리고 결제 모듈도 추가해줘", "complex"),
    # chaotic: pasted failures
    ("Traceback (most recent call last):\n  File \"x.py\", line 1", "chaotic"),
    ("the build crashed with an error: exit 2", "chaotic"),
]


@pytest.mark.parametrize("text,domain", CASES)
def test_classify(text: str, domain: str) -> None:
    assert cynefin.classify(text) == domain


def test_recent_failures_push_chaotic() -> None:
    assert cynefin.classify("add a flag", recent_failures=2) == "chaotic"
    assert cynefin.classify("add a flag", recent_failures=1) == "complicated"


def test_notes_are_ascii_and_bounded() -> None:
    for domain in cynefin.DOMAINS:
        note = cynefin.strategy_note(domain)
        assert note, domain
        assert note.isascii(), domain
        assert len(note.splitlines()) <= 6, domain
        assert note.startswith("Cynefin domain:"), domain


def test_unknown_domain_renders_empty() -> None:
    assert cynefin.strategy_note("nonsense") == ""


def test_defaults() -> None:
    assert config.DEFAULT_CONFIG["cynefin_enabled"] is True


@pytest.fixture()
def _bare_gate(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        promptgate, "_session_notes",
        lambda cfg, include_empty=False: "")


def test_promptgate_appends_note(_bare_gate) -> None:
    out = promptgate.compose_turn_context(
        {"cynefin_enabled": True, "ishikawa_enabled": False},
        user_text="fix the typo in README.md")
    assert "Cynefin domain: COMPLICATED." in out


def test_promptgate_disabled_flag(_bare_gate) -> None:
    out = promptgate.compose_turn_context(
        {"cynefin_enabled": False, "ishikawa_enabled": False},
        user_text="fix the typo in README.md")
    assert "Cynefin domain:" not in out


def test_promptgate_no_text_no_note(_bare_gate) -> None:
    out = promptgate.compose_turn_context(
        {"cynefin_enabled": True, "ishikawa_enabled": False})
    assert "Cynefin domain:" not in out


def test_promptgate_fail_open(_bare_gate,
                              monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("classifier exploded")
    monkeypatch.setattr(promptgate.cynefin, "note_for", boom)
    out = promptgate.compose_turn_context(
        {"cynefin_enabled": True, "ishikawa_enabled": False},
        user_text="fix the typo in README.md")
    assert out == ""
