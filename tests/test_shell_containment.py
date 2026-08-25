from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from birkin.tools import ToolContext
from birkin.tools import shell as shell_tool


def _context(workspace: Path, **cfg: object) -> ToolContext:
    return ToolContext(
        cfg={"shell_approval": "manual", **cfg},
        client=None,
        cwd=workspace,
    )


@pytest.mark.parametrize("escape_kind", ["absolute", "symlink"])
def test_shell_refuses_cwd_outside_configured_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    escape_kind: str,
) -> None:
    workspace = tmp_path / "workspace"
    external = tmp_path / "external"
    workspace.mkdir()
    external.mkdir()
    cwd = external
    if escape_kind == "symlink":
        cwd = workspace / "escape"
        try:
            cwd.symlink_to(external, target_is_directory=True)
        except OSError:
            pytest.skip("symlink creation is unavailable")
    monkeypatch.setattr(
        shell_tool,
        "run_shell_command",
        lambda _request: pytest.fail("escaped cwd reached subprocess"),
    )

    result = shell_tool._run_shell(
        {"command": "pwd", "cwd": str(cwd)},
        _context(workspace),
    )

    assert result.is_error is True
    assert "outside" in str(result.content).lower()


def test_shell_environment_forwards_only_mechanics_and_configured_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SYNTHETIC_PRIVATE_VALUE", "must-not-cross")
    monkeypatch.setenv("BIRKIN_SAFE_TEST_VALUE", "allowed-value")
    captured = []

    def run(request):
        captured.append(request)
        return subprocess.CompletedProcess([], 0, "ok", "")

    monkeypatch.setattr(shell_tool, "run_shell_command", run)

    result = shell_tool._run_shell(
        {"command": "printf ok"},
        _context(
            workspace,
            shell={
                "extra_roots": [],
                "env_passthrough": ["BIRKIN_SAFE_TEST_VALUE"],
            },
        ),
    )

    assert result.is_error is False
    environment = captured[0].environment
    assert "PATH" in environment
    assert environment["BIRKIN_SAFE_TEST_VALUE"] == "allowed-value"
    assert "SYNTHETIC_PRIVATE_VALUE" not in environment


def test_shell_wildcard_passthrough_restores_ambient_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SYNTHETIC_PRIVATE_VALUE", "operator-opted-in")
    captured = []
    monkeypatch.setattr(
        shell_tool,
        "run_shell_command",
        lambda request: (
            captured.append(request)
            or subprocess.CompletedProcess([], 0, "ok", "")
        ),
    )

    result = shell_tool._run_shell(
        {"command": "printf ok"},
        _context(
            workspace,
            shell={"extra_roots": [], "env_passthrough": ["*"]},
        ),
    )

    assert result.is_error is False
    assert (
        captured[0].environment["SYNTHETIC_PRIVATE_VALUE"]
        == "operator-opted-in"
    )


def test_shell_nested_extra_root_allows_explicit_external_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    external = tmp_path / "external"
    workspace.mkdir()
    external.mkdir()
    captured = []
    monkeypatch.setattr(
        shell_tool,
        "run_shell_command",
        lambda request: (
            captured.append(request)
            or subprocess.CompletedProcess([], 0, "ok", "")
        ),
    )

    result = shell_tool._run_shell(
        {"command": "pwd", "cwd": str(external)},
        _context(
            workspace,
            shell={
                "extra_roots": [str(external)],
                "env_passthrough": [],
            },
        ),
    )

    assert result.is_error is False
    assert captured[0].cwd == external
