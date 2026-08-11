"""Exact-operation approvals for retriable native-tool blocks."""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin import approvals, config, store
from birkin.tools import ToolContext, build_registry
from birkin.tools import shell as shell_mod


@pytest.fixture(autouse=True)
def _disable_unrelated_checkpoints() -> None:
    config.save_config({"checkpoints": False})


def test_fs_jail_block_queues_exact_manual_operation(tmp_path: Path) -> None:
    # Given: a file write outside an enforced workspace jail.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "outside.txt"
    registry = build_registry(ToolContext(
        cfg={"fs_jail": True, "auto_approve": ["operation"]},
        client=None,
        cwd=workspace,
    ), include={"files"})

    # When: the native write tool reaches the discretionary policy block.
    result = registry.execute(
        "write_file",
        {"path": str(target), "content": "approved only"},
    )

    # Then: nothing is written and the exact call waits for human approval.
    pending = store.list_pending()
    assert result.is_error
    assert "retry queued for approval" in result.content
    assert "Not run" not in result.content
    assert not target.exists()
    assert len(pending) == 1
    assert pending[0]["category"] == "operation"
    assert pending[0]["payload"]["operation"]["tool"] == "write_file"
    assert pending[0]["payload"]["operation"]["input"]["path"] == str(target)
    assert pending[0]["payload"]["operation"]["cwd"] == str(workspace.resolve())
    assert pending[0]["payload"]["digest"]


def test_permission_error_queues_operation_without_retrying(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Given: the OS refuses one otherwise ordinary file write.
    target = tmp_path / "denied.txt"
    original_write_text = Path.write_text
    attempts = 0

    def deny_target(path: Path, *args, **kwargs) -> int:
        nonlocal attempts
        if path == target:
            attempts += 1
            raise PermissionError("Access is denied")
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", deny_target)
    registry = build_registry(ToolContext(
        cfg={},
        client=None,
        cwd=tmp_path,
    ), include={"files"})

    # When: the tool reaches the OS permission boundary.
    result = registry.execute(
        "write_file",
        {"path": str(target), "content": "one attempt"},
    )

    # Then: it queues once rather than retrying or silently changing strategy.
    pending = store.list_pending()
    assert result.is_error
    assert "queued for approval" in result.content
    assert attempts == 1
    assert not target.exists()
    assert len(pending) == 1
    assert pending[0]["payload"]["operation"]["tool"] == "write_file"
    assert pending[0]["payload"]["operation"]["gate"] == "os_permission"


@pytest.mark.parametrize(
    ("command", "stderr", "gate"),
    [
        (
            "git status",
            "fatal: detected dubious ownership in repository\n"
            "To add an exception, call: git config --global --add "
            "safe.directory C:/repo",
            "git_safe_directory",
        ),
        (
            "omo --version",
            "omo.ps1 cannot be loaded because running scripts is disabled "
            "on this system. PSSecurityException",
            "powershell_execution_policy",
        ),
    ],
)
def test_execution_policy_diagnostics_queue_exact_operation(
    tmp_path: Path,
    monkeypatch,
    command: str,
    stderr: str,
    gate: str,
) -> None:
    # Given: a benign shell command reaches a host execution-policy boundary.
    calls: list[tuple[str, ...]] = []

    class FailedProcess:
        returncode = 1
        stdout = ""

        def __init__(self, error: str) -> None:
            self.stderr = error

    def blocked_run(argv: list[str], **_kwargs) -> FailedProcess:
        calls.append(tuple(argv))
        return FailedProcess(stderr)

    monkeypatch.setattr(shell_mod.subprocess, "run", blocked_run)
    registry = build_registry(ToolContext(
        cfg={},
        client=None,
        cwd=tmp_path,
    ), include={"shell"})

    # When: the command fails with a recognized policy diagnostic.
    result = registry.execute("run_shell", {"command": command, "timeout": 20})

    # Then: Birkin queues the exact command once instead of applying a bypass.
    pending = store.list_pending()
    assert result.is_error
    assert "retry queued for approval" in result.content
    assert "Not run" not in result.content
    assert len(calls) == 1
    assert len(pending) == 1
    operation = pending[0]["payload"]["operation"]
    assert operation["tool"] == "run_shell"
    assert operation["input"] == {"command": command, "timeout": 20}
    assert operation["gate"] == gate
    environment = operation["environment"]
    if gate == "git_safe_directory":
        assert environment == {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": str(tmp_path.resolve()),
        }
    else:
        assert environment == {"PSExecutionPolicyPreference": "Bypass"}


def test_approval_replays_exact_sealed_file_operation(tmp_path: Path) -> None:
    # Given: a jailed file write has been queued with its exact target/content.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "approved.txt"
    registry = build_registry(ToolContext(
        cfg={"fs_jail": True},
        client=None,
        cwd=workspace,
    ), include={"files"})
    result = registry.execute(
        "write_file",
        {"path": str(target), "content": "sealed content"},
    )
    pending = store.list_pending()
    assert pending, result.content
    approval_id = pending[0]["id"]

    # When: the human approves the stored operation.
    resolution = approvals.approve(approval_id)

    # Then: only the sealed write is replayed and recorded as approved.
    assert resolution["ok"] is True, resolution
    assert target.read_text(encoding="utf-8") == "sealed content"
    assert store.get_pending(approval_id)["status"] == "approved"
