from __future__ import annotations

import tomllib
from pathlib import Path


def test_pytest_ignores_local_comparison_worktrees() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    ignored = config["tool"]["pytest"]["ini_options"]["norecursedirs"]

    assert "tmp" in ignored
