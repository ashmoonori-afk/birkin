"""Approval recovery runs for approval-owning subcommands only."""

from __future__ import annotations

import pytest

from birkin import approval_execution_recovery, cli


class _RecoveryRan(RuntimeError):
    pass


@pytest.fixture()
def tripwire(monkeypatch: pytest.MonkeyPatch) -> None:
    def _explode() -> None:
        raise _RecoveryRan

    monkeypatch.setattr(approval_execution_recovery, "recover_all", _explode)


def test_help_does_not_recover_approvals(tripwire: None, capsys) -> None:
    # Given a parse-only invocation, When main() runs it
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["model", "--help"])

    # Then argparse exits without touching durable approval state
    assert exit_info.value.code == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_review_recovers_approvals(tripwire: None) -> None:
    # Given the review subcommand, When main() runs it
    # Then recovery runs before the command handler
    with pytest.raises(_RecoveryRan):
        cli.main(["review"])
