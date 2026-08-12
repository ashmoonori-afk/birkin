from __future__ import annotations

from pathlib import Path

import tomli


def test_pytest_ignores_local_comparison_worktrees() -> None:
    config = tomli.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    ignored = config["tool"]["pytest"]["ini_options"]["norecursedirs"]

    assert "tmp" in ignored
