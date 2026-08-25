from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

from birkin import config, plugin_runtime
from birkin.cli import build_parser, main
from birkin.plugin_install import PluginInstaller, Scope
from birkin.plugin_runtime import PluginActivationError, load_agent_tools
from birkin.plugin_signature import bundle_digest, sign_bundle
from birkin.skills.manager import build_manager

KEY = b"fixture-secret-key"


def _manifest(root: Path, *, kind: str, entry: str, version: str = "1.0.0",
              writes: bool = False, signed: bool = True) -> Path:
    root.mkdir(parents=True)
    target = root / entry.partition(":")[0]
    if kind == "skill":
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text(
            "---\nname: plugin-skill\ndescription: from registry\n---\nbody\n",
            encoding="utf-8",
        )
    else:
        target.write_text(
            "from birkin.tools import Tool, ToolResult\n"
            "def tools():\n"
            " return [Tool('plugin_echo', 'echo', {'type':'object'}, "
            "lambda inp, ctx: ToolResult('ok'))]\n",
            encoding="utf-8",
        )
    data = {
        "name": "plugin-skill" if kind == "skill" else "plugin-agent",
        "version": version,
        "kinds": [kind],
        "entry_points": {kind: [entry]},
        "required_permissions": {
            "network": "off", "network_allowlist": [], "env_allowlist": [],
            "write_paths": ["output"] if writes else [],
        },
        "unsigned_allowed": True,
    }
    (root / "birkin-plugin.json").write_text(json.dumps(data), encoding="utf-8")
    if signed:
        sign_bundle(root, "test", KEY)
    return root


def test_cli_inspect_has_machine_readable_permission_disclosure(tmp_path: Path, capsys):
    bundle = _manifest(tmp_path / "bundle", kind="skill", entry="skill", writes=True)
    key = f"test={KEY.hex()}"
    args = build_parser().parse_args(
        ["plugins", "inspect", str(bundle), "--json", "--key", key]
    )
    assert args.func.__name__ == "_cmd_plugins"

    assert main(
        ["plugins", "inspect", str(bundle), "--json", "--key", key]
    ) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["permissions"]["write_paths"] == ["output"]
    assert record["requires_confirmation"] is True


def test_cli_refuses_install_without_confirmation_then_installs_exact_pin(
    tmp_path: Path, monkeypatch, capsys
):
    home, project = tmp_path / "home", tmp_path / "project"
    project.mkdir()
    bundle = _manifest(tmp_path / "bundle", kind="skill", entry="skill", writes=True)
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    monkeypatch.chdir(project)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    argv = [
        "plugins",
        "install",
        str(bundle),
        "--version",
        "1.0.0",
        "--key",
        f"test={KEY.hex()}",
    ]
    assert main(argv) == 1
    assert "write_paths: output" in capsys.readouterr().out
    assert not (project / ".birkin" / "registry" / "registry.lock").exists()

    assert main([*argv, "--yes", "--json"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert json.loads(lines[-1])["version"] == "1.0.0"


def test_project_plugin_skills_shadow_team_scope(tmp_path: Path, monkeypatch):
    home, project = tmp_path / "home", tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    monkeypatch.chdir(project)
    installer = PluginInstaller(
        project / ".birkin" / "registry",
        home / "registry" / "team",
        {"test": KEY},
    )
    installer.install(
        _manifest(tmp_path / "team", kind="skill", entry="skill", version="1.0.0"),
        Scope.TEAM, "1.0.0",
    )
    installer.install(
        _manifest(tmp_path / "project-bundle", kind="skill", entry="skill", version="2.0.0"),
        Scope.PROJECT, "2.0.0",
    )

    cfg = {
        **config.DEFAULT_CONFIG,
        "plugins": {"trusted_keys": {"test": KEY.hex()}},
    }
    skill = build_manager(cfg).get("plugin-skill")
    assert skill is not None
    assert "2.0.0" in skill.source


def test_agent_entry_points_feed_existing_tool_registry_contract(tmp_path: Path):
    project, team = tmp_path / "project-registry", tmp_path / "team-registry"
    installer = PluginInstaller(project, team, {"test": KEY})
    installer.install(
        _manifest(tmp_path / "agent", kind="agent", entry="agent.py:tools"),
        Scope.PROJECT, "1.0.0", confirmed=True,
    )

    tools = load_agent_tools(project, team, {"test": KEY})
    assert [tool.name for tool in tools] == ["plugin_echo"]


def test_unsigned_lock_record_cannot_execute_agent_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    project, team = tmp_path / "project-registry", tmp_path / "team-registry"
    bundle = _manifest(
        project / "bundles" / "plugin-agent" / "1.0.0",
        kind="agent",
        entry="agent.py:tools",
        signed=False,
    )
    sentinel = tmp_path / "executed.txt"
    monkeypatch.setenv("BIRKIN_PLUGIN_SENTINEL", str(sentinel))
    (bundle / "agent.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "Path(os.environ['BIRKIN_PLUGIN_SENTINEL']).write_text('executed')\n"
        "def tools():\n"
        " return []\n",
        encoding="utf-8",
    )
    project.mkdir(parents=True, exist_ok=True)
    (project / "registry.lock").write_text(
        json.dumps(
            {
                "lock_version": 1,
                "scope": "project",
                "bundles": {
                    "plugin-agent": {
                        "version": "1.0.0",
                        "digest": bundle_digest(bundle),
                        "path": "bundles/plugin-agent/1.0.0",
                        "kinds": ["agent"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PluginActivationError, match="reinstall"):
        load_agent_tools(project, team)

    assert not sentinel.exists()


def test_plugin_activation_rejects_post_verification_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project-registry"
    team = tmp_path / "team-registry"
    installed = PluginInstaller(project, team, {"test": KEY}).install(
        _manifest(
            tmp_path / "agent-race",
            kind="agent",
            entry="agent.py:tools",
        ),
        Scope.PROJECT,
        "1.0.0",
        confirmed=True,
    )
    sentinel = tmp_path / "replacement-executed"
    monkeypatch.setenv("BIRKIN_PLUGIN_SENTINEL", str(sentinel))
    verified = threading.Event()
    release = threading.Event()
    original_verify = plugin_runtime.verify_bundle

    def verify_then_wait(
        root: Path,
        trusted_keys: dict[str, bytes],
        *,
        allow_missing: bool,
    ) -> tuple[str, str]:
        result = original_verify(
            root,
            trusted_keys,
            allow_missing=allow_missing,
        )
        if root == installed.path:
            verified.set()
            assert release.wait(timeout=2)
        return result

    monkeypatch.setattr(plugin_runtime, "verify_bundle", verify_then_wait)
    activation_errors: list[PluginActivationError] = []

    def activate() -> None:
        try:
            plugin_runtime.load_agent_tools(project, team, {"test": KEY})
        except PluginActivationError as exc:
            activation_errors.append(exc)

    thread = threading.Thread(target=activate)
    thread.start()
    assert verified.wait(timeout=2)
    try:
        (installed.path / "agent.py").write_text(
            "import os\n"
            "from pathlib import Path\n"
            "Path(os.environ['BIRKIN_PLUGIN_SENTINEL']).write_text("
            "'executed', encoding='utf-8')\n"
            "def tools():\n"
            " return []\n",
            encoding="utf-8",
        )
    finally:
        release.set()
        thread.join(timeout=2)
        sys.modules.pop(
            f"birkin_plugin_{installed.digest}_agent",
            None,
        )

    assert not thread.is_alive()
    assert len(activation_errors) == 1
    assert not sentinel.exists()
