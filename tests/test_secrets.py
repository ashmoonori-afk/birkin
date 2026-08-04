"""Resolving a credential from a secrets manager instead of a plaintext env var.

birkin reads an API key from the environment (config.PROVIDER_API_KEY_ENV ->
config.get_api_key) or, failing that, from config.json -- where the key sits in
plaintext on disk, inside the same directory the file tools already treat as a
control plane. Nothing reached a secrets manager, so a user who keeps
credentials in Bitwarden or 1Password had to export them by hand into the shell
that launches birkin, and every unattended surface (cron, gateway, a systemd
unit) needed the secret written down permanently somewhere.

A source resolves a reference at startup and puts the value into the process
environment, so get_api_key and every provider keep working unchanged. hermes
does the same thing (agent/secret_sources/registry.py apply_all); its Bitwarden
and 1Password backends shell out to the `bw` and `op` CLIs, which is why this
port needs no dependency: they are command sources with a known argv.
"""

from __future__ import annotations

import sys

import pytest

from birkin import config, secrets

VALUE = "sk-ant-api03-" + "QqWwEeRrTtYyUuIiOoPp"


def _echo(text: str) -> list[str]:
    """An argv that prints ``text`` -- a deterministic stand-in for `bw get`."""
    return [sys.executable, "-c", f"print({text!r})"]


@pytest.fixture()
def env() -> dict[str, str]:
    """A throwaway environment, so a test can never touch the real one."""
    return {}


class TestCommandSource:
    def test_stdout_becomes_the_secret(self, env) -> None:
        report = secrets.apply_all(
            {"secrets": {"ANTHROPIC_API_KEY": {"source": "command",
                                               "argv": _echo(VALUE)}}}, env=env)
        assert env["ANTHROPIC_API_KEY"] == VALUE
        assert report["applied"] == ["ANTHROPIC_API_KEY"]

    def test_trailing_newline_is_stripped(self, env) -> None:
        """`bw get` ends its output with a newline; a key with \\n in it 401s."""
        secrets.apply_all(
            {"secrets": {"K": {"source": "command", "argv": _echo(VALUE)}}},
            env=env)
        assert env["K"] == VALUE and "\n" not in env["K"]

    def test_a_failing_command_degrades_only_its_own_entry(self, env) -> None:
        cfg = {"secrets": {
            "GOOD": {"source": "command", "argv": _echo(VALUE)},
            "BAD": {"source": "command",
                    "argv": [sys.executable, "-c", "import sys; sys.exit(3)"]},
        }}
        report = secrets.apply_all(cfg, env=env)
        assert env.get("GOOD") == VALUE
        assert "BAD" not in env
        assert "BAD" in report["failed"]

    def test_a_hanging_command_cannot_wedge_startup(self, env) -> None:
        cfg = {"secrets": {"SLOW": {
            "source": "command",
            "argv": [sys.executable, "-c", "import time; time.sleep(30)"],
            "timeout": 0.4}}}
        report = secrets.apply_all(cfg, env=env)
        assert "SLOW" not in env
        assert "SLOW" in report["failed"]

    def test_empty_output_is_not_a_secret(self, env) -> None:
        report = secrets.apply_all(
            {"secrets": {"K": {"source": "command", "argv": _echo("")}}},
            env=env)
        assert "K" not in env
        assert "K" in report["failed"]


class TestExistingEnvironmentWins:
    def test_an_already_set_variable_is_preserved(self, env) -> None:
        """An operator's explicit export must beat a stored reference."""
        env["ANTHROPIC_API_KEY"] = "set-by-the-operator"
        report = secrets.apply_all(
            {"secrets": {"ANTHROPIC_API_KEY": {"source": "command",
                                               "argv": _echo(VALUE)}}}, env=env)
        assert env["ANTHROPIC_API_KEY"] == "set-by-the-operator"
        assert report["skipped"] == ["ANTHROPIC_API_KEY"]

    def test_an_empty_variable_is_not_treated_as_set(self, env) -> None:
        env["K"] = ""
        secrets.apply_all(
            {"secrets": {"K": {"source": "command", "argv": _echo(VALUE)}}},
            env=env)
        assert env["K"] == VALUE


class TestManagerBackends:
    def test_bitwarden_reference_becomes_a_bw_invocation(self) -> None:
        assert secrets.argv_for({"source": "bitwarden",
                                 "ref": "birkin/anthropic"}) == \
            ["bw", "get", "password", "birkin/anthropic"]

    def test_onepassword_reference_becomes_an_op_invocation(self) -> None:
        assert secrets.argv_for({"source": "op",
                                 "ref": "op://vault/openai/credential"}) == \
            ["op", "read", "--no-newline", "op://vault/openai/credential"]

    def test_an_unknown_source_is_refused(self) -> None:
        assert secrets.argv_for({"source": "telepathy", "ref": "x"}) is None

    def test_a_reference_is_required(self) -> None:
        assert secrets.argv_for({"source": "bitwarden"}) is None


class TestTheReportNeverCarriesTheSecret:
    def test_no_value_appears_in_the_report(self, env) -> None:
        """The report is printed at startup and can reach a log."""
        report = secrets.apply_all(
            {"secrets": {"K": {"source": "command", "argv": _echo(VALUE)}}},
            env=env)
        assert VALUE not in repr(report)

    def test_a_failure_reason_names_no_value(self, env) -> None:
        cfg = {"secrets": {"K": {"source": "command", "argv": [
            sys.executable, "-c",
            f"import sys; sys.stderr.write({VALUE!r}); sys.exit(1)"]}}}
        report = secrets.apply_all(cfg, env=env)
        assert VALUE not in repr(report)


class TestNoConfigurationIsANoOp:
    def test_absent_secrets_key(self, env) -> None:
        assert secrets.apply_all({}, env=env) == {
            "applied": [], "failed": {}, "skipped": []}
        assert env == {}

    def test_malformed_entry_is_reported_not_raised(self, env) -> None:
        report = secrets.apply_all({"secrets": {"K": "not-a-mapping"}}, env=env)
        assert "K" in report["failed"]


class TestGetApiKeyPicksItUp:
    def test_a_resolved_secret_reaches_config_get_api_key(self, monkeypatch) -> None:
        """The wiring, not just the module: the provider path must see it."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        cfg = {"provider": "anthropic", "api_key": None,
               "secrets": {"ANTHROPIC_API_KEY": {"source": "command",
                                                 "argv": _echo(VALUE)}}}
        assert config.get_api_key(cfg) is None
        secrets.apply_all(cfg)
        assert config.get_api_key(cfg) == VALUE
