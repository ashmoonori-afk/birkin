"""Windows shell smoke isolation regression coverage."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows shell smoke")
def test_windows_shell_smoke_prefers_its_path_fake_over_host_npm_shim(
    tmp_path: Path,
) -> None:
    # Given: a host-global Claude shim that conflicts with the smoke's PATH fake.
    host_appdata = tmp_path / "host-appdata"
    host_npm = host_appdata / "npm"
    host_npm.mkdir(parents=True)
    _ = (host_npm / "claude.cmd").write_text(
        "@echo off\r\necho host-global:%*\r\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["APPDATA"] = str(host_appdata)

    # When: the real Windows smoke harness runs under the polluted environment.
    result = subprocess.run(
        [sys.executable, "scripts/qa/windows_shell_smoke.py"],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        check=False,
        encoding="utf-8",
        env=environment,
        text=True,
    )

    # Then: its PATH-first fake, not the host-global shim, provides MCP output.
    assert '"mcp": "mcp-discrete:mcp list"' in result.stdout
