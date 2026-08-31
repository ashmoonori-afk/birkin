"""Security invariants for exact native-operation approvals."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from birkin import approval_execution, approvals, config, store
from birkin.tools import ToolContext, build_registry
from birkin.tools import files
from birkin.tools import shell as shell_mod


@pytest.fixture(autouse=True)
def _disable_unrelated_checkpoints() -> None:
    config.save_config({"checkpoints": False})


def _registry(tmp_path: Path, cfg: dict | None = None):
    return build_registry(
        ToolContext(
            cfg=cfg or {},
            client=None,
            cwd=tmp_path,
        )
    )


def test_disabled_native_tool_queues_instead_of_disappearing(
    tmp_path: Path,
) -> None:
    # Given: configuration disables a native shell tool.
    registry = _registry(tmp_path, {"disabled_tools": ["run_shell"]})
    assert "run_shell" not in registry.names()

    # When: an exact call still reaches the registry.
    result = registry.execute("run_shell", {"command": "echo blocked"})

    # Then: the denied call is reviewable rather than reported as unknown.
    pending = store.list_pending()
    assert result.is_error
    assert "queued for approval" in result.content
    assert len(pending) == 1
    operation = pending[0]["payload"]["operation"]
    assert operation["tool"] == "run_shell"
    assert operation["gate"] == "tool_policy"


def test_tampered_sealed_operation_fails_closed(tmp_path: Path) -> None:
    # Given: a valid queued file operation whose persisted input is mutated.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "target.txt"
    registry = _registry(workspace, {"fs_jail": True})
    registry.execute(
        "write_file",
        {"path": str(target), "content": "reviewed"},
    )
    approval_id = store.list_pending()[0]["id"]
    record_path = config.pending_dir() / f"{approval_id}.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["payload"]["operation"]["input"]["content"] = "substituted"
    record_path.write_text(json.dumps(record), encoding="utf-8")

    # When: approval executes the now-mismatched record.
    resolution = approvals.approve(approval_id, approved_by="human:test", approved_via="test")

    # Then: digest verification rejects it without side effects.
    assert resolution["ok"] is False
    assert "digest mismatch" in resolution["error"]
    assert not target.exists()
    assert store.get_pending(approval_id)["status"] == "error"


def test_approved_permission_failure_does_not_requeue(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Given: the OS denies both the original and explicitly approved retry.
    target = tmp_path / "denied.txt"
    attempts = 0

    def deny_target(*args, **kwargs):
        nonlocal attempts
        del args, kwargs
        attempts += 1
        raise PermissionError("Access is denied")

    monkeypatch.setattr(files, "open_for_write", deny_target)
    registry = _registry(tmp_path)
    registry.execute(
        "write_file",
        {"path": str(target), "content": "still denied"},
    )
    approval_id = store.list_pending()[0]["id"]

    # When: the one approved retry reaches the same OS boundary.
    resolution = approvals.approve(approval_id, approved_by="human:test", approved_via="test")

    # Then: it terminates as an error and creates no recursive approval.
    assert resolution["ok"] is False
    assert "Approved operation failed" in resolution["error"]
    assert attempts == 2
    assert store.list_pending() == []
    assert store.get_pending(approval_id)["status"] == "error"


def test_non_policy_shell_failure_is_not_queued(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Given: a command fails for an ordinary application reason.
    class FailedProcess:
        returncode = 1
        stdout = ""
        stderr = "assertion failed: expected 2, got 3"

    monkeypatch.setattr(
        shell_mod,
        "run_shell_command",
        lambda _request: FailedProcess(),
    )

    # When: the command returns its application failure.
    result = _registry(tmp_path).execute(
        "run_shell",
        {"command": "python failing_test.py"},
    )

    # Then: Birkin does not turn every nonzero exit into approval spam.
    assert result.is_error
    assert "[exit 1]" in result.content
    assert store.list_pending() == []


def test_control_plane_write_requires_then_honors_approval(
    tmp_path: Path,
) -> None:
    # Given: a direct native write targets Birkin scheduler state.
    target = config.birkin_home() / "cron.json"
    result = _registry(tmp_path).execute(
        "write_file",
        {"path": str(target), "content": '{"jobs": []}'},
    )
    pending = store.list_pending()
    assert result.is_error
    assert "queued for approval" in result.content
    assert not target.exists()

    # When: a human approves that exact control-plane write.
    resolution = approvals.approve(pending[0]["id"], approved_by="human:test", approved_via="test")

    # Then: the sealed operation is applied once.
    assert resolution["ok"] is True, resolution
    assert json.loads(target.read_text(encoding="utf-8")) == {"jobs": []}


def test_pending_approval_records_remain_integrity_protected(
    tmp_path: Path,
) -> None:
    # Given: a native file tool targets the approval store itself.
    target = config.pending_dir() / "forged.json"

    # When: it attempts to write an approval record.
    result = _registry(tmp_path).execute(
        "write_file",
        {"path": str(target), "content": "{}"},
    )

    # Then: this integrity boundary remains a hard stop, not approvable.
    assert result.is_error
    assert "integrity-protected" in result.content
    assert "queued for approval" not in result.content
    assert not target.exists()
    assert store.list_pending() == []


def test_approved_temp_policy_retry_uses_local_scoped_directories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Given: uv fails because the default cache/temp boundary is inaccessible.
    attempts = 0

    class Process:
        stdout = ""

        def __init__(self, returncode: int, stderr: str = "") -> None:
            self.returncode = returncode
            self.stderr = stderr

    def run(request) -> Process:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return Process(
                1,
                "Access is denied: C:\\Users\\me\\AppData\\Local\\Temp\\uv-cache",
            )
        environment = request.environment
        assert environment["TEMP"] == str(tmp_path / ".birkin-tmp")
        assert environment["TMP"] == str(tmp_path / ".birkin-tmp")
        assert environment["UV_CACHE_DIR"] == str(tmp_path / ".uv-cache")
        assert Path(environment["TEMP"]).is_dir()
        assert Path(environment["UV_CACHE_DIR"]).is_dir()
        return Process(0)

    monkeypatch.setattr(shell_mod, "run_shell_command", run)
    monkeypatch.setattr(approvals, "run_shell_command", run)
    registry = _registry(tmp_path)
    queued = registry.execute(
        "run_shell",
        {"command": "uv run pytest"},
    )
    approval_id = store.list_pending()[0]["id"]

    # When: the human approves the sealed local-temp retry profile.
    resolution = approvals.approve(approval_id, approved_by="human:test", approved_via="test")

    # Then: one retry receives only workspace-local environment overrides.
    assert "queued for approval" in queued.content
    assert resolution["ok"] is True, resolution
    assert attempts == 2


def test_approved_replay_does_not_queue_a_second_policy_gate(
    tmp_path: Path,
) -> None:
    # Given: tool policy blocks a shell call that has its own dangerous gate.
    registry = _registry(tmp_path, {"disabled_tools": ["run_shell"]})
    registry.execute(
        "run_shell",
        {"command": "rm -rf temporary-output"},
    )
    approval_id = store.list_pending()[0]["id"]

    # When: the tool-policy approval reaches shellguard during replay.
    resolution = approvals.approve(approval_id, approved_by="human:test", approved_via="test")

    # Then: the second gate is terminal and cannot recursively enqueue itself.
    assert resolution["ok"] is False
    assert "additional shell policy gate" in resolution["error"]
    assert store.list_pending() == []
    assert store.get_pending(approval_id)["status"] == "error"
