"""Distribution metadata keeps the dependency surface explicit."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TypedDict, cast

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


_ROOT = Path(__file__).resolve().parent.parent


class _Project(TypedDict):
    version: str
    dependencies: list[str]
    optional_dependencies: dict[str, list[str]]


def _project() -> _Project:
    with (_ROOT / "pyproject.toml").open("rb") as handle:
        raw = tomllib.load(handle)["project"]
    return {
        "version": cast("str", raw["version"]),
        "dependencies": cast("list[str]", raw["dependencies"]),
        "optional_dependencies": cast(
            "dict[str, list[str]]",
            raw["optional-dependencies"],
        ),
    }


def test_package_versions_match() -> None:
    from birkin import __version__

    assert _project()["version"] == __version__


def test_core_install_has_only_process_identity_dependency() -> None:
    assert _project()["dependencies"] == ["psutil>=6"]


def test_feature_extras_are_split_and_full_is_their_union() -> None:
    extras = _project()["optional_dependencies"]
    expected = {
        "voice": {"openai[realtime,voice_helpers]>=2.53,<3"},
        "desktop": {
            "Pillow>=11",
            "pyobjc-framework-ApplicationServices>=12.0; sys_platform == 'darwin'",
            "pyobjc-framework-Quartz>=12.0; sys_platform == 'darwin'",
            "python-xlib>=0.33; sys_platform == 'linux'",
            "pywinctl>=0.4.1; sys_platform == 'linux'",
            "pywinauto>=0.6.9; sys_platform == 'win32'",
            "pywin32>=308; sys_platform == 'win32'",
        },
        "office": {"openpyxl>=3.1,<4"},
        "browser": {"playwright>=1.54,<2"},
    }
    for name, packages in expected.items():
        assert set(extras[name]) == packages
    assert set(extras["full"]) == set().union(*expected.values())
    # Browser automation is intentionally absent from CI/dev installs; the
    # integration marker opts in only after Playwright Chromium is installed.
    assert set(extras["full"]) - expected["browser"] < set(extras["dev"])
    assert expected["browser"].isdisjoint(extras["dev"])
