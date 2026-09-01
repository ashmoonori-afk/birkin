from __future__ import annotations

from pathlib import Path

from script.qa.workspace_terminal_evidence import (
    EvidenceInputs,
    emit_terminal_evidence,
)
from script.qa.workspace_terminal_pty import (
    ChildExit,
    TerminalCapture,
    TerminalObservations,
    TerminalScenario,
)


def test_metadata_reports_typed_observations_not_transcript_prose(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    profile = tmp_path / "profile"
    profile.mkdir()
    scenario = TerminalScenario(
        transcript="approval unicode_paste interrupt reconnect prose only",
        captures=tuple(
            TerminalCapture(width=width, raw=f"capture-{width}")
            for width in (60, 80, 100, 120, 160)
        ),
        children=(
            ChildExit(pid=101, exit_code=0),
            ChildExit(pid=202, exit_code=0),
        ),
        observations=TerminalObservations(
            approval=False,
            unicode_paste=False,
            interrupt=False,
            reconnect=False,
        ),
        first_port=7001,
        reconnect_port=7002,
    )

    result = emit_terminal_evidence(
        EvidenceInputs(evidence=evidence, profile=profile, scenario=scenario)
    )

    assert result.ok
    metadata_text = (evidence / "terminal-pty.json").read_text(encoding="utf-8")
    assert '"approval": false' in metadata_text
    assert '"unicode_paste": false' in metadata_text
    assert '"interrupt": false' in metadata_text
    assert '"reconnect": false' in metadata_text
