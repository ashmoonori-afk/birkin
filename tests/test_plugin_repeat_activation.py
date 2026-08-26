from __future__ import annotations

import gc
import json
import sys
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest

from birkin import plugin_runtime
from birkin.plugin_install import InstalledPlugin, PluginInstaller, Scope
from birkin.plugin_runtime import PluginActivationError
from birkin.plugin_signature import sign_bundle
from birkin.plugin_snapshot import SnapshotLoader
from birkin.tools import ToolContext


KEY = b"repeat-activation-test-key"


class DeterministicFactoryError(RuntimeError):
    """Synthetic repeat-activation factory failure."""


def _repeatable_bundle(root: Path) -> Path:
    package = root / "plugin_package"
    package.mkdir(parents=True)
    (package / "helper.py").write_text(
        "VALUE = 'relative-import'\n",
        encoding="utf-8",
    )
    (package / "resource.txt").write_text(
        "package-resource",
        encoding="utf-8",
    )
    (package / "__init__.py").write_text(
        "from importlib.resources import files\n"
        "from birkin.tools import Tool, ToolResult\n"
        "from .helper import VALUE\n"
        "INITIAL_RESOURCE = files(__package__).joinpath("
        "'resource.txt').read_text(encoding='utf-8')\n"
        "def run(inp, ctx):\n"
        " resource = files(__package__).joinpath("
        "'resource.txt').read_text(encoding='utf-8')\n"
        " return ToolResult(VALUE + ':' + resource)\n"
        "def tools():\n"
        " return [Tool('repeat_package', 'package', "
        "{'type':'object'}, run)]\n",
        encoding="utf-8",
    )
    (root / "secondary.py").write_text(
        "import os\n"
        "from birkin.tools import Tool, ToolResult\n"
        "def tools():\n"
        " if os.environ.get('BIRKIN_REPEAT_FAIL') == '1':\n"
        "  raise RuntimeError('repeat activation failure')\n"
        " return [Tool('repeat_secondary', 'secondary', "
        "{'type':'object'}, lambda inp, ctx: ToolResult('ok'))]\n",
        encoding="utf-8",
    )
    (root / "birkin-plugin.json").write_text(
        json.dumps(
            {
                "name": "repeat-activation-agent",
                "version": "1.0.0",
                "kinds": ["agent"],
                "entry_points": {
                    "agent": [
                        "plugin_package/__init__.py:tools",
                        "secondary.py:tools",
                    ],
                },
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
    sign_bundle(root, "repeat-test", KEY)
    return root


def _install(
    tmp_path: Path,
) -> tuple[Path, Path, InstalledPlugin]:
    project = tmp_path / "project-registry"
    team = tmp_path / "team-registry"
    installed = PluginInstaller(
        project,
        team,
        {"repeat-test": KEY},
    ).install(
        _repeatable_bundle(tmp_path / "bundle"),
        Scope.PROJECT,
        "1.0.0",
        confirmed=True,
    )
    return project, team, installed


def _record_second_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> list[Path]:
    original = plugin_runtime._snapshot_plugin
    snapshots: list[Path] = []

    def record(
        plugin: InstalledPlugin,
        trusted_keys: Mapping[str, bytes],
        allow_unsigned: bool,
    ) -> tuple[
        Path,
        Mapping[str, bytes],
        tempfile.TemporaryDirectory[str],
    ]:
        result = original(plugin, trusted_keys, allow_unsigned)
        snapshots.append(result[0])
        return result

    monkeypatch.setattr(plugin_runtime, "_snapshot_plugin", record)
    return snapshots


def _cleanup_namespace(prefix: str) -> None:
    for name in tuple(sys.modules):
        if name.startswith(prefix):
            sys.modules.pop(name, None)
    gc.collect()


def test_failed_repeat_activation_restores_exact_prior_namespace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, team, installed = _install(tmp_path)
    prefix = f"birkin_plugin_{installed.digest}_"
    first_tools = plugin_runtime.load_agent_tools(
        project,
        team,
        {"repeat-test": KEY},
    )
    prior_modules = {
        name: module
        for name, module in sys.modules.items()
        if name.startswith(prefix)
    }
    prior_finders = {
        module.__loader__
        for module in prior_modules.values()
        if isinstance(module.__loader__, SnapshotLoader)
    }
    package_module = prior_modules[f"{prefix}__init__"]
    prior_snapshot = Path(package_module.__file__).parents[1]
    second_snapshots = _record_second_snapshot(monkeypatch)
    monkeypatch.setenv("BIRKIN_REPEAT_FAIL", "1")

    with pytest.raises(PluginActivationError):
        plugin_runtime.load_agent_tools(
            project,
            team,
            {"repeat-test": KEY},
        )

    try:
        assert prior_modules
        assert all(
            sys.modules.get(name) is module
            for name, module in prior_modules.items()
        )
        assert prior_finders
        assert all(finder in sys.meta_path for finder in prior_finders)
        assert prior_snapshot.exists()
        assert second_snapshots and not second_snapshots[0].exists()
        current_finders = {
            finder
            for finder in sys.meta_path
            if isinstance(finder, SnapshotLoader)
            and finder._module_name.startswith(prefix)
        }
        assert current_finders == prior_finders
        context = ToolContext(cfg={}, client=None, cwd=tmp_path)
        result = first_tools[0].fn({}, context)
        assert result.content == "relative-import:package-resource"
    finally:
        _cleanup_namespace(prefix)


def test_failed_repeat_activation_preserves_newer_module_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, team, installed = _install(tmp_path)
    prefix = f"birkin_plugin_{installed.digest}_"
    first_tools = plugin_runtime.load_agent_tools(
        project,
        team,
        {"repeat-test": KEY},
    )
    prior_finders = {
        finder
        for finder in sys.meta_path
        if isinstance(finder, SnapshotLoader)
        and finder._module_name.startswith(prefix)
    }
    second_snapshots = _record_second_snapshot(monkeypatch)
    original_load = plugin_runtime.load_snapshot_module
    factory_entered = threading.Event()
    release_factory = threading.Event()
    second_modules: list[ModuleType] = []

    def load_then_block_factory(*args, **kwargs):
        module = original_load(*args, **kwargs)
        second_modules.append(module)
        if module.__name__ == f"{prefix}secondary":
            def fail() -> None:
                factory_entered.set()
                assert release_factory.wait(timeout=5)
                raise DeterministicFactoryError(
                    "deterministic winner failure"
                )

            module.tools = fail
        return module

    monkeypatch.setattr(
        plugin_runtime,
        "load_snapshot_module",
        load_then_block_factory,
    )
    errors: list[PluginActivationError] = []

    def activate() -> None:
        try:
            plugin_runtime.load_agent_tools(
                project,
                team,
                {"repeat-test": KEY},
            )
        except PluginActivationError as exc:
            errors.append(exc)

    thread = threading.Thread(target=activate)
    thread.start()
    assert factory_entered.wait(timeout=5)
    winner = ModuleType(f"{prefix}secondary")
    sys.modules[winner.__name__] = winner
    release_factory.set()
    thread.join(timeout=5)

    try:
        assert not thread.is_alive()
        assert len(errors) == 1
        assert sys.modules.get(winner.__name__) is winner
        assert second_modules
        assert all(module is not winner for module in second_modules)
        assert second_snapshots and not second_snapshots[0].exists()
        assert all(finder in sys.meta_path for finder in prior_finders)
        assert not any(
            module.__loader__ in sys.meta_path
            for module in second_modules
        )
    finally:
        del first_tools
        _cleanup_namespace(prefix)
