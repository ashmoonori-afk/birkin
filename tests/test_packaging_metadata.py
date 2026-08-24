"""Distribution metadata keeps the dependency surface explicit."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TypedDict, cast

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


_ROOT = Path(__file__).resolve().parent.parent

# The core install stays deliberately small. `birkin-mnemosyne` is the one
# git-sourced runtime dependency (role-profile review), and it is pinned to an
# immutable commit so a moved tag cannot silently change what ships.
_CORE_DEPENDENCIES = [
    "psutil>=6",
    "typing-extensions>=4.12",
    "birkin-mnemosyne @ git+https://github.com/ashmoonori-afk"
    "/birkin-mnemosyne@36814c13b44260a0c1ada53d142b2940fff134df",
]


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


def test_pre_commit_hook_does_not_mutate_package_version(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    package = repository / "birkin"
    hook = repository / "scripts/hooks/pre-commit"
    package.mkdir(parents=True)
    hook.parent.mkdir(parents=True)
    init = package / "__init__.py"
    project = repository / "pyproject.toml"
    _ = init.write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    _ = project.write_text(
        '[project]\nname = "birkin"\nversion = "1.2.3"\n',
        encoding="utf-8",
    )
    _ = hook.write_bytes((_ROOT / "scripts/hooks/pre-commit").read_bytes())
    _ = subprocess.run(
        ["git", "init", "--quiet"],
        cwd=repository,
        check=True,
    )

    result = subprocess.run(
        ["sh", str(hook)],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert init.read_text(encoding="utf-8") == '__version__ = "1.2.3"\n'
    assert project.read_text(encoding="utf-8") == (
        '[project]\nname = "birkin"\nversion = "1.2.3"\n'
    )
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    assert staged.stdout == ""


def test_core_install_has_only_required_runtime_dependencies() -> None:
    assert _project()["dependencies"] == _CORE_DEPENDENCIES


def test_feature_extras_are_split_and_full_is_their_union() -> None:
    extras = _project()["optional_dependencies"]
    expected = {
        "voice": {"openai[realtime,voice_helpers]>=2.53,<3"},
        "desktop": {
            "Pillow>=11,<13",
            "pyobjc-framework-ApplicationServices>=12.0; sys_platform == 'darwin'",
            "pyobjc-framework-Quartz>=12.0; sys_platform == 'darwin'",
            "python-xlib>=0.33; sys_platform == 'linux'",
            "pywinctl>=0.4.1; sys_platform == 'linux'",
            "pywinauto>=0.6.9; sys_platform == 'win32'",
            "pywin32>=308; sys_platform == 'win32'",
        },
        "office": {
            "jsonschema>=4.23,<5", "rfc8785>=0.1.4,<1",
            "defusedxml>=0.7,<1", "lxml>=5.3,<7",
            "openpyxl>=3.1.5,<4", "python-docx>=1.2,<2",
            "python-hwpx==6.1.0", "python-pptx>=1.0.2,<2",
        },
        "office-advanced": {
            "Pillow>=11,<13", "pypdf>=5.9,<7", "pypdfium2>=4.30,<5",
        },
        "browser": {"playwright>=1.54,<2"},
        "research": {"jsonschema>=4.23,<5", "rfc8785>=0.1.4,<1"},
        "work": {"jsonschema>=4.23,<5", "rfc8785>=0.1.4,<1"},
    }
    for name, packages in expected.items():
        assert set(extras[name]) == packages
    assert set(extras["full"]) == set().union(*expected.values())
    # New P3 distributions and browser automation stay absent from core CI.
    pre_p3_dev = expected["voice"] | expected["desktop"] | {"openpyxl>=3.1.5,<4"}
    assert set(extras["dev"]) >= pre_p3_dev
    assert expected["browser"].isdisjoint(extras["dev"])


def test_p3_extras_are_optional_and_core_ci_installs_no_new_p3_distributions() -> None:
    extras = _project()["optional_dependencies"]
    assert _project()["dependencies"] == _CORE_DEPENDENCIES
    assert {"office", "office-advanced", "office-docling", "research", "work"} <= extras.keys()
    forbidden = {"jsonschema", "rfc8785", "defusedxml", "lxml", "python-docx", "python-pptx", "pypdf", "pypdfium2", "docling"}
    assert not any(req.split("[",1)[0].split(">",1)[0] in forbidden for req in extras["dev"])
    assert not any(req.startswith("docling") for req in extras["full"])
