"""The packaging files must stay machine-readable.

A BOM written by a PowerShell heredoc made pyproject.toml unparseable —
`pytest` refused to start and `pip install` would have failed, on a commit
that was already pushed. Nothing in the suite noticed, because every test
imports the package rather than reading its metadata.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# `requires-python = ">=3.10"`, but the dev/CI Windows suite runs 3.13, so a
# 3.11+ `typing` name imports fine here and only explodes on the 3.10 job.
TYPING_ABOVE_3_10 = {
    "assert_never", "assert_type", "clear_overloads", "dataclass_transform",
    "get_overloads", "LiteralString", "Never", "NoDefault", "ReadOnly",
    "reveal_type", "Self", "TypeAliasType", "TypeIs", "TypeVarTuple",
    "Unpack", "override",
}


@pytest.mark.parametrize("rel", ["pyproject.toml", "birkin/__init__.py",
                                 "README.md", "README.ko.md"])
def test_no_byte_order_mark(rel):
    raw = (ROOT / rel).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), f"{rel} starts with a BOM"


def test_pyproject_parses_and_agrees_with_the_package_version():
    try:
        import tomllib
    except ModuleNotFoundError:                      # py3.10
        pytest.skip("tomllib needs Python 3.11+")
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    import birkin
    assert data["project"]["version"] == birkin.__version__


def test_desktop_extra_declares_runtime_dependencies():
    try:
        import tomllib
    except ModuleNotFoundError:                      # py3.10
        pytest.skip("tomllib needs Python 3.11+")
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    desktop = data["project"]["optional-dependencies"]["desktop"]
    assert any(requirement.startswith("pillow") for requirement in desktop)
    assert any(requirement.startswith("pywin32") for requirement in desktop)


def test_no_typing_name_newer_than_the_python_floor():
    offenders = []
    for path in sorted((ROOT / "birkin").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "typing":
                for alias in node.names:
                    if alias.name in TYPING_ABOVE_3_10:
                        rel = path.relative_to(ROOT).as_posix()
                        offenders.append(f"{rel}:{node.lineno} {alias.name}")
    assert not offenders, "typing names needing Python 3.11+: " + ", ".join(offenders)


def test_source_files_end_with_a_newline():
    for rel in ("pyproject.toml", "birkin/__init__.py"):
        raw = (ROOT / rel).read_bytes()
        assert raw.endswith(b"\n"), f"{rel} has no trailing newline"
