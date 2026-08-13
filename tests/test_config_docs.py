from __future__ import annotations

from pathlib import Path

from scripts.generate_config_docs import generate


def test_generated_config_docs_are_current() -> None:
    root = Path(__file__).resolve().parent.parent

    assert generate(root, check=True) == 0


def test_generated_config_references_cover_nested_defaults() -> None:
    root = Path(__file__).resolve().parent.parent
    english = (root / "docs/config-reference.md").read_text(encoding="utf-8")
    korean = (root / "docs/config-reference.ko.md").read_text(encoding="utf-8")

    for path in ("provider", "voice.sample_rate", "channels.telegram.stream"):
        assert f"`{path}`" in english
        assert f"`{path}`" in korean
