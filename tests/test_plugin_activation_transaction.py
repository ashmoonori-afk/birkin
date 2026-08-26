from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import pytest
from typing_extensions import assert_never

from birkin import plugin_runtime
from birkin.plugin_install import InstalledPlugin, PluginInstaller, Scope
from birkin.plugin_runtime import PluginActivationError
from birkin.plugin_signature import sign_bundle
from birkin.plugin_snapshot import SnapshotLoader


KEY = b"activation-transaction-test-key"
Failure = Literal[
    "entry_execution",
    "relative_import",
    "factory",
    "tool_validation",
]


def _failing_bundle(root: Path, failure: Failure) -> tuple[Path, str]:
    root.mkdir()
    match failure:
        case "entry_execution":
            entry = "agent.py:tools"
            source = "raise RuntimeError('entry execution failure')\n"
        case "relative_import":
            entry = "plugin_package/__init__.py:tools"
            package = root / "plugin_package"
            package.mkdir()
            source = "from .missing import tools\n"
            (package / "__init__.py").write_text(
                source,
                encoding="utf-8",
            )
            source = ""
        case "factory":
            entry = "agent.py:tools"
            source = (
                "def tools():\n"
                " raise RuntimeError('factory failure')\n"
            )
        case "tool_validation":
            entry = "agent.py:tools"
            source = (
                "def tools():\n"
                " return ['not-a-tool']\n"
            )
        case unreachable:
            assert_never(unreachable)
    entry_path = root / entry.partition(":")[0]
    if source:
        entry_path.write_text(source, encoding="utf-8")
    (root / "birkin-plugin.json").write_text(
        json.dumps(
            {
                "name": "transaction-agent",
                "version": "1.0.0",
                "kinds": ["agent"],
                "entry_points": {"agent": [entry]},
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
    sign_bundle(root, "transaction-test", KEY)
    return root, entry


@pytest.mark.parametrize(
    "failure",
    [
        "entry_execution",
        "relative_import",
        "factory",
        "tool_validation",
    ],
)
def test_failed_plugin_activation_rolls_back_all_snapshot_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Failure,
) -> None:
    project = tmp_path / "project-registry"
    team = tmp_path / "team-registry"
    bundle, _ = _failing_bundle(tmp_path / "bundle", failure)
    installed = PluginInstaller(
        project,
        team,
        {"transaction-test": KEY},
    ).install(
        bundle,
        Scope.PROJECT,
        "1.0.0",
        confirmed=True,
    )
    original_snapshot = plugin_runtime._snapshot_plugin
    snapshots: list[Path] = []

    def record_snapshot(
        plugin: InstalledPlugin,
        trusted_keys: dict[str, bytes],
        allow_unsigned: bool,
    ) -> tuple[
        Path,
        Mapping[str, bytes],
        tempfile.TemporaryDirectory[str],
    ]:
        result = original_snapshot(
            plugin,
            trusted_keys,
            allow_unsigned,
        )
        snapshots.append(result[0])
        return result

    monkeypatch.setattr(
        plugin_runtime,
        "_snapshot_plugin",
        record_snapshot,
    )
    prefix = f"birkin_plugin_{installed.digest}_"

    with pytest.raises(PluginActivationError):
        plugin_runtime.load_agent_tools(
            project,
            team,
            {"transaction-test": KEY},
        )

    assert snapshots
    assert not snapshots[0].exists()
    assert not any(name.startswith(prefix) for name in sys.modules)
    assert not any(
        isinstance(finder, SnapshotLoader)
        and finder._module_name.startswith(prefix)
        for finder in sys.meta_path
    )
