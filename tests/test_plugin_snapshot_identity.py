from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

from birkin import plugin_runtime
from birkin.plugin_install import PluginInstaller, Scope
from birkin.plugin_runtime import PluginActivationError
from birkin.plugin_signature import sign_bundle


KEY = b"snapshot-identity-test-key"


def _bundle(root: Path, entry: str = "agent.py:tools") -> Path:
    root.mkdir()
    entry_path = root / entry.partition(":")[0]
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    entry_path.write_text(
        "from birkin.tools import Tool, ToolResult\n"
        "def tools():\n"
        " return [Tool('snapshot_echo', 'snapshot', {'type':'object'}, "
        "lambda inp, ctx: ToolResult('ok'))]\n",
        encoding="utf-8",
    )
    (root / "birkin-plugin.json").write_text(
        json.dumps(
            {
                "name": "snapshot-agent",
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
    sign_bundle(root, "snapshot-test", KEY)
    return root


def test_plugin_snapshot_rejects_post_verification_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project-registry"
    team = tmp_path / "team-registry"
    installed = PluginInstaller(
        project,
        team,
        {"snapshot-test": KEY},
    ).install(
        _bundle(tmp_path / "bundle"),
        Scope.PROJECT,
        "1.0.0",
        confirmed=True,
    )
    sentinel = tmp_path / "snapshot-replacement-executed"
    monkeypatch.setenv("BIRKIN_SNAPSHOT_SENTINEL", str(sentinel))
    original_verify = plugin_runtime.verify_bundle
    snapshot_verified = threading.Event()
    release = threading.Event()
    snapshot_path: Path | None = None

    def verify_then_wait(
        root: Path,
        trusted_keys: dict[str, bytes],
        *,
        allow_missing: bool,
    ) -> tuple[str, str]:
        nonlocal snapshot_path
        result = original_verify(
            root,
            trusted_keys,
            allow_missing=allow_missing,
        )
        if root != installed.path and root.name == "bundle":
            snapshot_path = root
            snapshot_verified.set()
            assert release.wait(timeout=5)
        return result

    monkeypatch.setattr(plugin_runtime, "verify_bundle", verify_then_wait)
    activation_errors: list[PluginActivationError] = []

    def activate() -> None:
        try:
            plugin_runtime.load_agent_tools(
                project,
                team,
                {"snapshot-test": KEY},
            )
        except PluginActivationError as exc:
            activation_errors.append(exc)

    thread = threading.Thread(target=activate)
    thread.start()
    assert snapshot_verified.wait(timeout=5)
    assert snapshot_path is not None
    try:
        (snapshot_path / "agent.py").write_text(
            "import os\n"
            "from pathlib import Path\n"
            "Path(os.environ['BIRKIN_SNAPSHOT_SENTINEL']).write_text("
            "'executed', encoding='utf-8')\n"
            "def tools():\n"
            " return []\n",
            encoding="utf-8",
        )
    finally:
        release.set()
        thread.join(timeout=5)
        sys.modules.pop(
            f"birkin_plugin_{installed.digest}_agent",
            None,
        )

    assert not thread.is_alive()
    assert len(activation_errors) == 1
    assert not sentinel.exists()


def test_plugin_snapshot_preserves_package_imports_and_resources(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project-registry"
    team = tmp_path / "team-registry"
    bundle = _bundle(
        tmp_path / "package-bundle",
        "plugin_package/__init__.py:tools",
    )
    package = bundle / "plugin_package"
    (package / "helper.py").write_text(
        "DESCRIPTION = 'relative-import'\n",
        encoding="utf-8",
    )
    (package / "description.txt").write_text(
        "package-resource",
        encoding="utf-8",
    )
    (package / "__init__.py").write_text(
        "from importlib.resources import files\n"
        "from birkin.tools import Tool, ToolResult\n"
        "from .helper import DESCRIPTION\n"
        "RESOURCE = files(__package__).joinpath("
        "'description.txt').read_text(encoding='utf-8')\n"
        "def tools():\n"
        " return [Tool('snapshot_echo', DESCRIPTION + ':' + RESOURCE, "
        "{'type':'object'}, lambda inp, ctx: ToolResult('ok'))]\n",
        encoding="utf-8",
    )
    (bundle / "bundle.sig").unlink()
    sign_bundle(bundle, "snapshot-test", KEY)
    installed = PluginInstaller(
        project,
        team,
        {"snapshot-test": KEY},
    ).install(
        bundle,
        Scope.PROJECT,
        "1.0.0",
        confirmed=True,
    )
    module_name = f"birkin_plugin_{installed.digest}___init__"

    try:
        [tool] = plugin_runtime.load_agent_tools(
            project,
            team,
            {"snapshot-test": KEY},
        )
        assert tool.description == "relative-import:package-resource"
    finally:
        sys.modules.pop(f"{module_name}.helper", None)
        sys.modules.pop(module_name, None)
