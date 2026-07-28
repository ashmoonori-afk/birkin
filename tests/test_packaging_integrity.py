"""The packaging files must stay machine-readable.

A BOM written by a PowerShell heredoc made pyproject.toml unparseable —
`pytest` refused to start and `pip install` would have failed, on a commit
that was already pushed. Nothing in the suite noticed, because every test
imports the package rather than reading its metadata.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


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


def test_source_files_end_with_a_newline():
    for rel in ("pyproject.toml", "birkin/__init__.py"):
        raw = (ROOT / rel).read_bytes()
        assert raw.endswith(b"\n"), f"{rel} has no trailing newline"
