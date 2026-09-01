"""Tests for the canonical morpheus command and its legacy alias."""

from __future__ import annotations


def test_morpheus_canonical_parses():
    # Given the canonical subcommand name
    from birkin.cli import build_parser

    parser = build_parser()

    # When it is parsed with its only flag
    ns = parser.parse_args(["morpheus", "--dry-run"])

    # Then it routes to the morpheus command with the flag preserved
    assert ns.command == "morpheus"
    assert ns.dry_run is True
    assert ns.func.__name__ == "_cmd_morpheus"


def test_nightly_alias_invokes_morpheus(monkeypatch):
    # Given an offline morpheus run and no approval recovery
    from birkin import approval_execution_recovery, cli, morpheus

    runs: list[bool] = []

    def _record(dry_run: bool) -> int:
        runs.append(dry_run)
        return 0

    monkeypatch.setattr(approval_execution_recovery, "recover_all", lambda: None)
    monkeypatch.setattr(morpheus, "run_once", _record)

    # When the legacy alias is invoked
    exit_code = cli.main(["nightly", "--dry-run"])

    # Then the canonical command ran once, with the dry-run flag intact
    assert exit_code == 0
    assert runs == [True]
