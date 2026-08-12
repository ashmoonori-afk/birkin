"""Secret references resolve at startup, through the config load every surface uses.

birkin/secrets can resolve a credential, but a module nothing calls protects
nobody. Every surface -- the CLI, the MCP server, the gateway, cron -- reaches
its configuration through config.load_config(), which makes that the one place
a reference can become an environment variable before any provider asks for a
key.

It must happen at most ONCE per process. A manager lookup spawns `bw` or `op`,
and a single run calls load_config() many times; resolving on each of them would
turn one credential into a subprocess storm (and, with a vault that prompts for
unlock, into a wall of prompts).
"""

from __future__ import annotations

import json
import sys

import pytest

from birkin import config

VALUE = "sk-ant-api03-" + "AaBbCcDdEeFfGgHhIiJj"


def _recording_argv(marker, value: str) -> list[str]:
    """An argv that prints ``value`` and appends one byte to ``marker``.

    Counting the marker's bytes counts the subprocess spawns, with no mocking:
    the test observes the real child process, not a stand-in for it.
    """
    return [sys.executable, "-c",
            f"open({str(marker)!r}, 'a').write('x'); print({value!r})"]


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # The once-per-process latch has to start fresh for each test.
    monkeypatch.setattr(config, "_secrets_resolved", False, raising=False)
    return tmp_path


def _write_config(payload: dict) -> None:
    config.config_path().write_text(
        json.dumps({"provider": "anthropic", **payload}), encoding="utf-8")


class TestLoadConfigResolvesSecrets:
    def test_a_configured_reference_reaches_the_environment(self, home) -> None:
        marker = home / "calls"
        _write_config({"secrets": {"ANTHROPIC_API_KEY": {
            "source": "command", "argv": _recording_argv(marker, VALUE)}}})
        cfg = config.load_config()
        assert config.get_api_key(cfg) == VALUE

    def test_it_resolves_at_most_once_per_process(self, home) -> None:
        marker = home / "calls"
        _write_config({"secrets": {"ANTHROPIC_API_KEY": {
            "source": "command", "argv": _recording_argv(marker, VALUE)}}})
        config.load_config()
        first = marker.read_text(encoding="utf-8")
        config.load_config()
        config.load_config()
        assert marker.read_text(encoding="utf-8") == first == "x"

    def test_no_secrets_configured_spawns_nothing(self, home) -> None:
        _write_config({"model": "claude-sonnet-4-6"})
        config.load_config()
        assert not (home / "calls").exists()
        assert config.get_api_key({"provider": "anthropic"}) is None

    def test_an_exported_key_is_not_overwritten(self, home, monkeypatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "exported-by-the-operator")
        marker = home / "calls"
        _write_config({"secrets": {"ANTHROPIC_API_KEY": {
            "source": "command", "argv": _recording_argv(marker, VALUE)}}})
        cfg = config.load_config()
        assert config.get_api_key(cfg) == "exported-by-the-operator"

    def test_a_broken_reference_does_not_stop_startup(self, home) -> None:
        _write_config({"secrets": {"ANTHROPIC_API_KEY": {
            "source": "command",
            "argv": [sys.executable, "-c", "import sys; sys.exit(7)"]}}})
        cfg = config.load_config()          # must not raise
        assert cfg["model"]                  # defaults still merged
        assert config.get_api_key(cfg) is None
