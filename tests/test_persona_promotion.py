"""Promotion of approved mask guidance into SOUL.md."""

from __future__ import annotations

import pytest

from birkin import persona


def test_promotion_appends_and_preserves_existing_soul(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    persona.write_soul("# Existing SOUL\n\nOriginal voice stays.")

    persona.promote_guidance("- Prefer terse answers.")

    text = persona.soul_path().read_text(encoding="utf-8")
    assert text.startswith("# Existing SOUL\n\nOriginal voice stays.")
    assert "## Promoted guidance\n- Prefer terse answers." in text


def test_promotion_is_idempotent_on_repeat(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    persona.write_soul("# Existing")

    persona.promote_guidance("- No filler.")
    first = persona.soul_path().read_text(encoding="utf-8")
    persona.promote_guidance("- No filler.")
    second = persona.soul_path().read_text(encoding="utf-8")

    assert first == second
    assert second.count("- No filler.") == 1


def test_promotion_creates_soul_without_truncating_guidance(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))

    persona.promote_guidance("- New promoted guidance")

    assert persona.read_soul() == "## Promoted guidance\n- New promoted guidance"


def test_failed_promotion_write_does_not_corrupt_soul(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    persona.write_soul("# Existing\nkeep me")

    def boom(self, target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(persona.Path, "replace", boom)
    with pytest.raises(OSError):
        persona.promote_guidance("- New guidance")

    assert persona.read_soul() == "# Existing\nkeep me"
    assert not list(tmp_path.glob("*.tmp"))
