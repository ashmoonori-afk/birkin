from __future__ import annotations

import json
from pathlib import Path

from birkin import config
from birkin.cli import build_parser, main
from birkin.plugin_install import PluginInstaller, Scope
from birkin.plugin_runtime import load_agent_tools
from birkin.skills.manager import build_manager


def _manifest(root: Path, *, kind: str, entry: str, version: str = "1.0.0",
              writes: bool = False) -> Path:
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
    return root


def test_cli_inspect_has_machine_readable_permission_disclosure(tmp_path: Path, capsys):
    bundle = _manifest(tmp_path / "bundle", kind="skill", entry="skill", writes=True)
    args = build_parser().parse_args(["plugins", "inspect", str(bundle), "--json"])
    assert args.func.__name__ == "_cmd_plugins"

    assert main(["plugins", "inspect", str(bundle), "--json"]) == 0
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

    argv = ["plugins", "install", str(bundle), "--version", "1.0.0"]
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
        project / ".birkin" / "registry", home / "registry" / "team"
    )
    installer.install(
        _manifest(tmp_path / "team", kind="skill", entry="skill", version="1.0.0"),
        Scope.TEAM, "1.0.0",
    )
    installer.install(
        _manifest(tmp_path / "project-bundle", kind="skill", entry="skill", version="2.0.0"),
        Scope.PROJECT, "2.0.0",
    )

    skill = build_manager(config.DEFAULT_CONFIG).get("plugin-skill")
    assert skill is not None
    assert "2.0.0" in skill.source


def test_agent_entry_points_feed_existing_tool_registry_contract(tmp_path: Path):
    project, team = tmp_path / "project-registry", tmp_path / "team-registry"
    installer = PluginInstaller(project, team)
    installer.install(
        _manifest(tmp_path / "agent", kind="agent", entry="agent.py:tools"),
        Scope.PROJECT, "1.0.0",
    )

    tools = load_agent_tools(project, team)
    assert [tool.name for tool in tools] == ["plugin_echo"]
