"""/permission slash: unattended-full toggle + the /permissions alias."""

from __future__ import annotations

import types

from birkin import config, slashcommands


def _sess():
    return types.SimpleNamespace(
        cfg={**config.DEFAULT_CONFIG},
        client=types.SimpleNamespace(cli_access="workspace"))


def test_permissions_alias_registered():
    assert slashcommands._ALIASES.get("permissions") == "permission"
    assert "permissions" in slashcommands._REGISTRY["permission"].aliases


def test_unattended_full_toggle(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    s = _sess()
    slashcommands._permission(s, "unattended-full on")
    assert s.cfg["allow_unattended_full"] is True
    assert config.load_config()["allow_unattended_full"] is True   # persisted
    slashcommands._permission(s, "unattended-full off")
    assert s.cfg["allow_unattended_full"] is False


def test_access_full_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    s = _sess()
    slashcommands._permission(s, "access full")
    assert s.cfg["cli_access"] == "full" and s.client.cli_access == "full"
