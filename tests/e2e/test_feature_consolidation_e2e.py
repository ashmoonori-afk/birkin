"""Production-path contracts for consolidated feature surfaces."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from birkin import checkpoints, config, delivery, lineage, scheduler
from birkin import workspace_theme as legacy_theme
from birkin.gateway.channels import discord_webhook, slack_webhook
from birkin.plugin_manifest import ManifestError, load_manifest
from birkin.workspace import theme as canonical_theme


def _webhook_url(channel: str) -> str:
    host = "hooks.slack.com" if channel == "slack" else "discord.com"
    return f"https://{host}/{channel}"


def _patch_webhook_opener(
    monkeypatch: pytest.MonkeyPatch,
    channel: str,
    open_request,
) -> None:
    module = slack_webhook if channel == "slack" else discord_webhook

    class Opener:
        @staticmethod
        def open(request, timeout):
            return open_request(request, timeout)

    monkeypatch.setattr(module, "pinned_opener", lambda: Opener())


def _cli(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["BIRKIN_HOME"] = str(home)
    env["NO_COLOR"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "birkin", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_legacy_theme_is_a_true_canonical_reexport() -> None:
    assert legacy_theme.PALETTES is canonical_theme.PALETTES
    assert legacy_theme.contract is canonical_theme.contract
    assert legacy_theme.web_variables is canonical_theme.web_variables


def test_cli_tool_inventory_comes_from_every_canonical_group(
    tmp_path: Path,
) -> None:
    result = _cli(tmp_path, "tools")

    assert result.returncode == 0, result.stderr
    for group in ("browser:", "documents:", "plugins:"):
        assert group in result.stdout


def test_sessions_export_nested_parser_accepts_trailing_options(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "demo.json").write_text(
        json.dumps([{"role": "user", "content": "hello"}]),
        encoding="utf-8",
    )

    result = _cli(tmp_path, "sessions", "export", "demo", "--vault")

    assert result.returncode == 0, result.stdout + result.stderr
    assert list(
        (tmp_path / "vault" / "journal").glob("*demo.md")
    ), result.stdout + result.stderr
    assert "skipped" not in result.stdout


@pytest.mark.parametrize("kind", ["hook", "mcp_server"])
def test_plugin_manifest_rejects_non_activatable_kinds(
    tmp_path: Path,
    kind: str,
) -> None:
    manifest = tmp_path / "birkin-plugin.json"
    manifest.write_text(
        json.dumps(
            {
                "name": "unsafe-kind",
                "version": "1.0.0",
                "kinds": [kind],
                "entry_points": {kind: ["entry.py:run"]},
                "required_permissions": {
                    "network": "off",
                    "network_allowlist": [],
                    "env_allowlist": [],
                    "write_paths": [],
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ManifestError, match="not activatable"):
        load_manifest(manifest)


def test_worker_hook_cli_is_a_deprecated_driver_alias() -> None:
    with TemporaryDirectory(
        prefix="birkin-worker-hook-",
        dir=Path(__file__).resolve().parents[2],
    ) as private_parent_raw:
        private_parent = Path(private_parent_raw)
        if os.name != "nt":
            private_parent.chmod(0o700)
            assert private_parent.stat().st_mode & 0o022 == 0
        result = _cli(
            private_parent / "home",
            "worker-hook-qa",
            "--decision",
            "approve",
        )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "deprecated" in result.stderr.lower()
    assert json.loads(result.stdout)["ok"] is True


@pytest.mark.parametrize("channel", ["slack", "discord"])
def test_send_only_channels_have_policy_gated_scheduler_producer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    channel: str,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    config.save_config(
        {
            **config.DEFAULT_CONFIG,
            "channels": {
                channel: {
                    "enabled": True,
                    "webhook_url": _webhook_url(channel),
                    "allowed_channel_ids": ["ops"],
                }
            },
        }
    )
    requests: list[urllib.request.Request] = []

    class Response:
        status = 204

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b""

    def urlopen(
        request: urllib.request.Request,
        timeout: int,
    ) -> Response:
        assert timeout == 15
        requests.append(request)
        return Response()

    _patch_webhook_opener(monkeypatch, channel, urlopen)
    result = scheduler._deliver(
        {
            "name": "daily",
            "deliver_channel": channel,
            "deliver_chat_id": "ops",
        },
        "verified output",
    )

    assert result == "sent"
    assert len(requests) == 1
    assert delivery.pending(channel) == []


@pytest.mark.parametrize("channel", ["slack", "discord"])
def test_send_only_channels_replay_pending_delivery_on_scheduler_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    channel: str,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    config.save_config(
        {
            **config.DEFAULT_CONFIG,
            "channels": {
                channel: {
                    "enabled": True,
                    "webhook_url": _webhook_url(channel),
                    "allowed_channel_ids": ["ops"],
                }
            },
        }
    )
    requests: list[urllib.request.Request] = []

    class Response:
        status = 204

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b""

    _patch_webhook_opener(
        monkeypatch,
        channel,
        lambda request, timeout: requests.append(request) or Response(),
    )
    delivery.record(channel, "ops", "recover me")

    assert scheduler.redeliver_send_only_channels() == 1
    assert len(requests) == 1
    assert delivery.pending(channel) == []


@pytest.mark.parametrize("channel", ["slack", "discord"])
def test_send_only_channels_keep_revoked_destinations_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    channel: str,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    config.save_config(
        {
            **config.DEFAULT_CONFIG,
            "channels": {
                channel: {
                    "enabled": True,
                    "webhook_url": _webhook_url(channel),
                    "allowed_channel_ids": [],
                }
            },
        }
    )
    requests: list[urllib.request.Request] = []
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout: requests.append(request),
    )
    delivery.record(channel, "revoked", "keep private")

    assert scheduler.redeliver_send_only_channels() == 0
    assert requests == []
    assert len(delivery.pending(channel)) == 1


@pytest.mark.parametrize("channel", ["slack", "discord"])
def test_send_only_channels_refuse_unrecorded_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    channel: str,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    config.save_config(
        {
            **config.DEFAULT_CONFIG,
            "channels": {
                channel: {
                    "enabled": True,
                    "webhook_url": _webhook_url(channel),
                    "allowed_channel_ids": ["ops"],
                }
            },
        }
    )
    requests: list[urllib.request.Request] = []
    monkeypatch.setattr(delivery, "record", lambda *_args: None)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout: requests.append(request),
    )

    result = scheduler._deliver(
        {
            "name": "daily",
            "deliver_channel": channel,
            "deliver_chat_id": "ops",
        },
        "verified output",
    )

    assert result == "error: could not record delivery obligation"
    assert requests == []


def test_lineage_supports_trusted_recovery_export_and_prune(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    first_messages = [{"role": "user", "content": "first"}]
    second_messages = [{"role": "user", "content": "second"}]
    first = lineage.snapshot(first_messages)
    second = lineage.snapshot(second_messages, parent=first)

    assert [entry["id"] for entry in lineage.list_snapshots()] == [
        second,
        first,
    ]
    assert lineage.recover(first) == first_messages
    exported = lineage.export_snapshot(second, tmp_path / "export.json")
    assert exported == tmp_path / "export.json"
    assert json.loads(exported.read_text(encoding="utf-8"))["trusted"] is True
    assert lineage.prune(keep=1) == [first]
    assert lineage.load(first) is None
    with pytest.raises(ValueError, match="snapshot id"):
        lineage.recover("../config")


def test_lineage_lifecycle_is_available_through_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    snapshot_id = lineage.snapshot([{"role": "user", "content": "recover"}])
    assert snapshot_id
    listed = _cli(tmp_path, "lineage", "list")
    recovered = _cli(tmp_path, "lineage", "recover", snapshot_id)
    exported = _cli(
        tmp_path,
        "lineage",
        "export",
        snapshot_id,
        str(tmp_path / "snapshot.json"),
    )

    assert listed.returncode == 0 and snapshot_id in listed.stdout
    assert recovered.returncode == 0 and "recover" in recovered.stdout
    assert exported.returncode == 0
    assert (tmp_path / "snapshot.json").is_file()


def test_checkpoint_task_restore_uses_canonical_state_bridge(
    tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    source = work / "main.py"
    source.write_text("before\n", encoding="utf-8")
    state: dict[str, Any] = {
        "session_id": "checkpoint-e2e",
        "working_memory": {"text": "before"},
        "goal": {"objective": "ship"},
    }
    restored: list[checkpoints.CanonicalStateSnapshot] = []
    manager = checkpoints.CheckpointManager(
        store_dir=tmp_path / "store",
        state_snapshot=lambda: json.loads(json.dumps(state)),
        state_restore=restored.append,
    )
    commit = manager.ensure_checkpoint(work, "before edit")
    assert commit
    state["working_memory"]["text"] = "after"
    source.write_text("after\n", encoding="utf-8")

    outcome = manager.restore(work, commit, mode=checkpoints.RestoreMode.TASK)

    assert outcome.task_restored is True
    assert outcome.files_restored is False
    assert restored == [
        checkpoints.CanonicalStateSnapshot(
            session_id="checkpoint-e2e",
            working_memory={"text": "before"},
            goal={"objective": "ship"},
        )
    ]
    assert source.read_text(encoding="utf-8") == "after\n"
