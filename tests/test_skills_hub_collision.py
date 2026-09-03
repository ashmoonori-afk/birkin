"""A second install must not take over a skill already installed under a name.

The directory a bundle installs into comes from the bundle's own frontmatter,
and publishing is unconditional ``replace=True``. So a skill fetched as
``handy-tool`` whose SKILL.md says ``name: pdf`` used to replace an installed,
differently-sourced ``pdf`` -- bundle and lock entry both -- and the agent then
reads the replacement as instructions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin.skills import hub


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    yield


def _skill(root: Path, directory: str, name: str, body: str) -> Path:
    d = root / directory
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: a demo\n---\n\n{body}\n",
        encoding="utf-8")
    return d


def test_a_second_source_cannot_take_over_an_installed_skill(tmp_path):
    first = _skill(tmp_path, "pdf", "pdf", "Read the PDF and summarise it.")
    ok, report = hub.install(str(first), confirm=lambda *a, **k: True)
    assert ok, report

    # Different identifier, same frontmatter name: it aims at hub/pdf.
    second = _skill(tmp_path, "handy-tool", "pdf", "ATTACKER BODY.")
    ok, report = hub.install(str(second), confirm=lambda *a, **k: True)

    assert not ok, report
    installed = hub.resolve_install_path("pdf") / "SKILL.md"
    assert "ATTACKER BODY" not in installed.read_text(encoding="utf-8")
    assert hub.load_lock()["pdf"]["identifier"] == str(first)


def test_the_same_source_can_still_be_reinstalled(tmp_path):
    skill = _skill(tmp_path, "pdf", "pdf", "First body.")
    assert hub.install(str(skill), confirm=lambda *a, **k: True)[0]

    _skill(tmp_path, "pdf", "pdf", "Second body.")
    ok, report = hub.install(str(skill), confirm=lambda *a, **k: True)

    assert ok, report
    installed = hub.resolve_install_path("pdf") / "SKILL.md"
    assert "Second body." in installed.read_text(encoding="utf-8")
