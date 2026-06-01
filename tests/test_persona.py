"""Unit tests for the editable persona (SOUL.md) layer + prompt integration."""

from __future__ import annotations

from birkin import persona, prompts


def test_read_empty_when_no_soul(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    assert persona.read_soul() == ""
    assert persona.soul_path() == tmp_path / "SOUL.md"


def test_seed_default_creates_then_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    assert persona.seed_default() is True          # first time -> writes
    assert persona.seed_default() is False         # already exists -> no-op
    assert persona.soul_path().is_file()
    assert "persona" in persona.read_soul().lower()


def test_seed_force_overwrites(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    persona.write_soul("# mine\nbe terse")
    assert persona.seed_default() is False          # respects existing
    assert persona.seed_default(force=True) is True
    assert "be terse" not in persona.read_soul()


def test_write_and_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    persona.write_soul("# custom\narr, a pirate i be")
    assert "pirate" in persona.read_soul()


def test_presets_present():
    assert {"warm", "concise", "mentor", "direct"} <= set(persona.PRESETS)
    for body in persona.PRESETS.values():
        assert body.strip()


def test_persona_replaces_identity_in_system_prompt():
    soul = "# pirate\nArr, talk like a pirate."
    out = prompts.build_system_prompt(persona=soul)
    assert "pirate" in out.lower()
    assert "You are birkin — a warm, sharp" not in out  # default identity replaced


def test_persona_replaces_identity_in_cli_system():
    soul = "# pirate\nArr, talk like a pirate."
    out = prompts.build_cli_system(persona=soul)
    assert "pirate" in out.lower()


def test_blank_persona_falls_back_to_default():
    out = prompts.build_system_prompt(persona="   ")
    assert "birkin" in out.lower()  # default identity used


def test_write_soul_cleans_tmp_on_replace_failure(monkeypatch):
    import pytest
    persona.write_soul("first")
    assert persona.read_soul() == "first"

    def boom(self, target):
        raise OSError("simulated replace failure (Windows window)")

    monkeypatch.setattr(persona.Path, "replace", boom)
    with pytest.raises(OSError):
        persona.write_soul("second")
    assert persona.read_soul() == "first"               # original intact
    assert not list(persona.soul_path().parent.glob("*.tmp"))  # no .tmp leak
