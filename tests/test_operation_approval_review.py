"""Regressions from the independent global-approval security review."""

from __future__ import annotations

from pathlib import Path

from birkin import (
    approval_execution,
    approvals,
    checkpoints,
    config,
    hooks,
    security,
    store,
)
from birkin.gateway.channels.telegram import _payload_summary
from birkin.tools import ToolContext, build_registry
from birkin.tools import shell as shell_mod


def test_reserved_approved_environment_cannot_enter_pending_payload(
    tmp_path: Path,
) -> None:
    # Given: model input tries to smuggle executor-only environment values.
    registry = build_registry(
        ToolContext(
            cfg={"disabled_tools": ["run_shell"]},
            client=None,
            cwd=tmp_path,
        )
    )

    # When: a blocked tool call includes the reserved replay field.
    result = registry.execute(
        "run_shell",
        {
            "command": "git status",
            "_approved_env": {
                "GIT_CONFIG_KEY_0": "core.sshCommand",
                "GIT_CONFIG_VALUE_0": "smuggled",
            },
        },
    )

    # Then: Birkin refuses to seal or queue model-owned executor metadata.
    assert result.is_error
    assert "reserved" in result.content
    assert store.list_pending() == []


def test_shell_cannot_directly_rewrite_pending_approval_records(
    tmp_path: Path,
) -> None:
    # Given: a shell command directly names Birkin's approval record store.
    target = config.pending_dir() / "forged.json"
    registry = build_registry(
        ToolContext(
            cfg={"shell_approval": "off"},
            client=None,
            cwd=tmp_path,
        ),
        include={"shell"},
    )
    command = (
        'python -c "from pathlib import Path; '
        f"Path(r'{target}').write_text('forged')\""
    )

    # When: the native shell tool receives that control-plane mutation.
    result = registry.execute("run_shell", {"command": command})

    # Then: shellguard treats approval records as a hard integrity boundary.
    assert result.is_error
    assert "never run by birkin" in result.content
    assert not target.exists()
    assert store.list_pending() == []


def test_untrusted_command_output_cannot_forge_permission_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Given: an ordinary child process prints a policy-looking string.
    class FailedProcess:
        returncode = 1
        stdout = ""
        stderr = "permission denied"

    monkeypatch.setattr(
        shell_mod,
        "run_shell_command",
        lambda _request: FailedProcess(),
    )
    registry = build_registry(
        ToolContext(
            cfg={},
            client=None,
            cwd=tmp_path,
        ),
        include={"shell"},
    )

    # When: a non-policy command returns that untrusted diagnostic text.
    result = registry.execute(
        "run_shell",
        {"command": "echo harmless"},
    )

    # Then: the application failure stays terminal and cannot impersonate OS.
    assert result.is_error
    assert "[exit 1]" in result.content
    assert store.list_pending() == []


def test_approved_replay_keeps_checkpoint_and_hook_observers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Given: an approved file replay with checkpoint and hook observers.
    events: list[str] = []

    class FakeCheckpointManager:
        enabled = True

    class FakeHookBus:
        def pre_tool(self, _name, _input):
            events.append("hook:pre")
            return None

        def post_tool(self, _name, _input, _content, _is_error):
            events.append("hook:post")

    monkeypatch.setattr(
        checkpoints,
        "CheckpointManager",
        lambda **_kwargs: FakeCheckpointManager(),
    )
    monkeypatch.setattr(
        checkpoints,
        "preflight",
        lambda *_args, **_kwargs: events.append("checkpoint"),
    )
    monkeypatch.setattr(hooks, "build_bus", lambda _cfg: FakeHookBus())
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "approved.txt"
    registry = build_registry(
        ToolContext(
            cfg={"fs_jail": True},
            client=None,
            cwd=workspace,
        ),
        include={"files"},
    )
    registry.execute(
        "write_file",
        {"path": str(target), "content": "observed"},
    )
    approval_id = store.list_pending()[0]["id"]

    # When: approval replays the digest-bound operation.
    resolution = approvals.approve(approval_id, approved_by="human:test", approved_via="test")

    # Then: replay remains checkpointed and visible to both hook phases.
    assert resolution["ok"] is True, resolution
    assert events == ["hook:pre", "checkpoint", "hook:post"]


def test_telegram_operation_summary_keeps_review_critical_fields() -> None:
    # Given: a long command that would push gate/environment past raw truncation.
    payload = {
        "operation": {
            "version": 1,
            "tool": "run_shell",
            "input": {"command": "x" * 2000},
            "cwd": "C:/workspace",
            "gate": "powershell_execution_policy",
            "environment": {"PSExecutionPolicyPreference": "Bypass"},
        },
        "digest": "abcdef0123456789" * 4,
    }

    # When: Telegram renders the operation for one-tap review.
    summary = _payload_summary("operation", payload)

    # Then: critical authorization fields remain visible after input preview.
    assert "tool: run_shell" in summary
    assert "gate: powershell_execution_policy" in summary
    assert "cwd: C:/workspace" in summary
    assert "PSExecutionPolicyPreference=Bypass" in summary
    assert "digest: abcdef0123456789" in summary
    assert len(summary) < 3500


def test_operation_auto_approve_config_warns_that_it_is_inert() -> None:
    warnings = security.gateway_warnings(
        {
            "provider": "claude-cli",
            "auto_approve": ["operation"],
        }
    )

    assert any(
        "operation" in warning and "always manual" in warning for warning in warnings
    )


def test_identical_blocked_operations_share_one_pending_record(
    tmp_path: Path,
) -> None:
    # Given: one exact jailed file operation is emitted twice.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "outside.txt"
    registry = build_registry(
        ToolContext(
            cfg={"fs_jail": True},
            client=None,
            cwd=workspace,
        ),
        include={"files"},
    )
    tool_input = {"path": str(target), "content": "same"}

    # When: the model retries before the human reviews the first proposal.
    first = registry.execute("write_file", tool_input)
    second = registry.execute("write_file", tool_input)

    # Then: one digest maps to one pending record and one review decision.
    pending = store.list_pending()
    assert len(pending) == 1
    approval_id = pending[0]["id"]
    assert approval_id in first.content
    assert approval_id in second.content
    assert "already queued" in second.content
