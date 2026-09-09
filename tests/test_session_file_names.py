"""User-supplied session names must stay inside ``sessions_dir()``.

``/sessions save ../config`` used to write ``sessions/../config.json`` --
Birkin's own configuration file -- and ``/sessions load`` could read any
``*.json`` the process could reach.
"""

from __future__ import annotations

import json

import pytest

from birkin import config, sessions_export, slashcommands


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    yield tmp_path


class _Agent:
    def __init__(self) -> None:
        self.messages = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]


class _Session:
    def __init__(self) -> None:
        self.agent = _Agent()


@pytest.mark.parametrize("name", ["../config", "..", "sub/inner", "sub\\inner", ""])
def test_session_file_rejects_paths_outside_sessions_dir(name):
    assert config.session_file(name) is None


def test_session_file_accepts_plain_stem():
    assert config.session_file("20260909-120000") == (
        config.sessions_dir() / "20260909-120000.json")


def test_save_with_traversal_name_does_not_write_outside_sessions(_home, capsys):
    config_json = _home / "config.json"
    config_json.write_text("{}", encoding="utf-8")

    slashcommands._save(_Session(), "../config")

    assert config_json.read_text(encoding="utf-8") == "{}"
    assert not list(config.sessions_dir().glob("*.json"))
    assert "plain file names" in capsys.readouterr().out


def test_load_with_traversal_name_does_not_read_outside_sessions(_home, capsys):
    (_home / "secret.json").write_text(
        json.dumps([{"role": "user", "content": []}]), encoding="utf-8")
    session = _Session()
    before = list(session.agent.messages)

    slashcommands._load(session, "../secret")

    assert session.agent.messages == before
    assert "No session" in capsys.readouterr().out


def test_export_with_traversal_name_is_not_found(_home):
    (_home / "secret.json").write_text("[]", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        sessions_export.export("../secret")
