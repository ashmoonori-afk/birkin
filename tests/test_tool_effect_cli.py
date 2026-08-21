"""CLI contract for user-owned plugin tool effect attestations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from birkin.cli import main
from birkin.plugin_install import InstalledPlugin, PluginInstaller, Scope


def _install_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    plugin: str = "plugin-agent",
    tool: str = "plugin_echo",
    version: str = "1.0.0",
) -> InstalledPlugin:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    monkeypatch.chdir(project)

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "agent.py").write_text(
        "from birkin.tools import Tool, ToolResult\n"
        "def tools():\n"
        f" return Tool({tool!r}, 'plugin tool', {{'type': 'object'}}, "
        "lambda _input, _ctx: ToolResult('ok'))\n",
        encoding="utf-8",
    )
    manifest = {
        "name": plugin,
        "version": version,
        "kinds": ["agent"],
        "entry_points": {"agent": ["agent.py:tools"]},
        "required_permissions": {
            "network": "off",
            "network_allowlist": [],
            "env_allowlist": [],
            "write_paths": [],
        },
        "unsigned_allowed": True,
    }
    (bundle / "birkin-plugin.json").write_text(
        json.dumps(manifest), encoding="utf-8")
    installer = PluginInstaller(
        project / ".birkin" / "registry", home / "registry" / "team")
    return installer.install(bundle, Scope.PROJECT, version)


def _effect_path(tmp_path: Path) -> Path:
    return tmp_path / "home" / "tool-effects.json"


def test_list_missing_file_matches_literal_stdout_without_creating_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _install_agent(tmp_path, monkeypatch)

    assert main(["plugins", "effects", "list"]) == 0

    assert capsys.readouterr().out == (
        "plugin-agent@1.0.0/plugin_echo  change  serial  default:no-grant\n"
        "summary  inspect=0  change=1  stale=0\n"
    )
    assert not _effect_path(tmp_path).exists()


def test_set_list_and_revoke_round_trip_is_bound_to_installed_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    installed = _install_agent(tmp_path, monkeypatch)
    path = _effect_path(tmp_path)

    assert main([
        "plugins", "effects", "set", "plugin-agent", "plugin_echo",
        "inspect", "--parallel-safe", "--reason", "reviewed handler; no writes",
    ]) == 0
    assert capsys.readouterr().out == (
        "Recorded inspect grant for plugin-agent@1.0.0/plugin_echo.\n"
        f"digest  {installed.digest}\n"
        "schedule  parallel\n"
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["inspect_grants"][0]["bundle_digest"] == installed.digest

    assert main(["plugins", "effects", "list"]) == 0
    listed = capsys.readouterr().out
    assert "plugin-agent@1.0.0/plugin_echo  inspect  parallel  grant:" in listed

    assert main([
        "plugins", "effects", "set", "plugin-agent", "plugin_echo", "change",
    ]) == 0
    assert "Recorded change posture" in capsys.readouterr().out
    assert json.loads(path.read_text(encoding="utf-8"))["inspect_grants"] == []

    assert main(["plugins", "effects", "list"]) == 0
    assert "change  serial  default:no-grant" in capsys.readouterr().out


def test_inspect_without_reason_exits_one_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _install_agent(tmp_path, monkeypatch)

    assert main([
        "plugins", "effects", "set", "plugin-agent", "plugin_echo", "inspect",
    ]) == 1

    assert capsys.readouterr().out == (
        "Tool effect error: inspect requires a non-empty --reason.\n")
    assert not _effect_path(tmp_path).exists()


def test_malformed_effect_is_rejected_without_changing_existing_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _install_agent(tmp_path, monkeypatch)
    path = _effect_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    original = b'{"schema_version": 1, "inspect_grants": []}\n'
    path.write_bytes(original)

    assert main([
        "plugins", "effects", "set", "plugin-agent", "plugin_echo", "read-only",
    ]) == 1

    assert capsys.readouterr().out == (
        "Tool effect error: effect must be 'inspect' or 'change'.\n")
    assert path.read_bytes() == original


def test_unknown_action_names_the_valid_actions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["plugins", "effects", "frobnicate"]) == 1
    assert capsys.readouterr().out == (
        "Unknown tool-effects action 'frobnicate'; "
        "valid actions: list, prune, reset, set\n"
    )


def test_unknown_plugin_target_is_a_semantic_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    assert main([
        "plugins", "effects", "set", "missing", "echo", "inspect",
        "--reason", "reviewed",
    ]) == 1

    assert capsys.readouterr().out == (
        "Tool effect error: unknown or inactive plugin tool 'missing/echo'.\n")
    assert not (tmp_path / "bk" / "tool-effects.json").exists()


def test_broken_file_lists_conservative_rows_and_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _install_agent(tmp_path, monkeypatch)
    path = _effect_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{oops}", encoding="utf-8")

    assert main(["plugins", "effects", "list"]) == 1

    assert capsys.readouterr().out == (
        "Tool effect file error: invalid JSON at line 1 column 2.\n"
        "plugin-agent@1.0.0/plugin_echo  change  serial  invalid-file\n"
        "summary  inspect=0  change=1  stale=0\n"
    )


@pytest.mark.parametrize("command", [
    ["prune"],
    ["set", "plugin-agent", "plugin_echo", "inspect", "--reason", "reviewed"],
])
def test_broken_file_refuses_set_and_prune(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: list[str],
) -> None:
    _install_agent(tmp_path, monkeypatch)
    path = _effect_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    original = b"{oops}"
    path.write_bytes(original)

    assert main(["plugins", "effects", *command]) == 1

    assert capsys.readouterr().out == (
        "Tool effect file error: invalid JSON at line 1 column 2.\n")
    assert path.read_bytes() == original


def test_reset_requires_yes_then_backs_up_before_replacing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    path = _effect_path(tmp_path)
    path.parent.mkdir(parents=True)
    original = b"{precious malformed bytes}"
    path.write_bytes(original)

    assert main(["plugins", "effects", "reset"]) == 1
    assert capsys.readouterr().out == (
        "Tool effect error: reset requires --yes.\n")
    assert path.read_bytes() == original
    assert not path.with_name("tool-effects.json.previous").exists()

    assert main(["plugins", "effects", "reset", "--yes"]) == 0
    assert capsys.readouterr().out == (
        "Reset tool effects; previous bytes saved as tool-effects.json.previous.\n")
    assert path.with_name("tool-effects.json.previous").read_bytes() == original
    assert json.loads(path.read_text(encoding="utf-8"))["inspect_grants"] == []


def test_json_is_exactly_one_sorted_parseable_object_on_success_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _install_agent(tmp_path, monkeypatch)

    assert main(["plugins", "effects", "--json"]) == 0
    success_text = capsys.readouterr().out
    assert len(success_text.splitlines()) == 1
    success = json.loads(success_text)
    assert success_text == json.dumps(success, sort_keys=True) + "\n"
    assert success["summary"] == {"change": 1, "inspect": 0, "stale": 0}

    assert main([
        "plugins", "effects", "set", "missing", "echo", "inspect",
        "--reason", "reviewed", "--json",
    ]) == 1
    failure_text = capsys.readouterr().out
    assert len(failure_text.splitlines()) == 1
    failure = json.loads(failure_text)
    assert failure_text == json.dumps(failure, sort_keys=True) + "\n"
    assert set(failure) == {"error"}
