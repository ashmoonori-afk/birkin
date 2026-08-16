"""Installed-package contracts for unused-feature consolidation."""

from __future__ import annotations

import importlib.util
from importlib.metadata import distribution


def test_office_extra_keeps_the_xlsx_backend_contract() -> None:
    requirements = distribution("birkin").metadata.get_all("Requires-Dist") or []

    assert any(
        requirement.startswith("openpyxl")
        and ">=3.1.5" in requirement
        and "<4" in requirement
        and "extra == 'office'" in requirement
        for requirement in requirements
    )


def test_canonical_browser_aside_imports_without_shadow_modules() -> None:
    canonical = (
        "birkin.browser_aside_service",
        "birkin.browser_aside_playwright",
        "birkin.browser_aside_lifecycle",
    )
    shadows = (
        "birkin.browser_aside_frames",
        "birkin.browser_aside_session",
    )

    assert all(importlib.util.find_spec(module) is not None for module in canonical)
    assert all(importlib.util.find_spec(module) is None for module in shadows)
