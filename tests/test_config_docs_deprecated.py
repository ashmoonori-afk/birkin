"""Deprecated schema keys must render a real description, not an empty cell.

Regression for scripts/generate_config_docs.py: a ``deprecated`` property
(``nightly_hour``/``nightly_minute``) has no ``description``/
``x-description-ko`` of its own, so the generator used to print an empty
description cell for it in both language references.
"""

from __future__ import annotations

from scripts.generate_config_docs import render_reference

_SCHEMA = {
    "x-birkin-version": 1,
    "properties": {
        "nightly_hour": {
            "type": "integer",
            "deprecated": True,
            "x-replaced-by": "morpheus_hour",
        },
    },
}


def test_deprecated_key_gets_an_english_description() -> None:
    rendered = render_reference(_SCHEMA, "en")

    assert "| `nightly_hour` |" in rendered
    assert "Deprecated: use morpheus_hour" in rendered


def test_deprecated_key_gets_a_korean_description() -> None:
    rendered = render_reference(_SCHEMA, "ko")

    assert "폐기됨: morpheus_hour 사용" in rendered
