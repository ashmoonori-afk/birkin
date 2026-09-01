"""Drive portable terminal QA and emit typed, digest-verified evidence."""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import pexpect

from script.qa.workspace_terminal_evidence import (
    EvidenceError,
    EvidenceInputs,
    emit_terminal_evidence,
    verify_evidence,
)
from script.qa.workspace_terminal_pty import run_terminal_scenario

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / ".omo" / "evidence" / "terminal-workspace"


def _evidence_argument(argv: Sequence[str] | None = None) -> Path:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    match arguments:
        case ():
            return EVIDENCE.resolve()
        case ("--evidence-dir", raw):
            return Path(raw).resolve()
        case _:
            parser = argparse.ArgumentParser()
            _ = parser.add_argument("--evidence-dir", type=Path, default=EVIDENCE)
            parser.error("expected --evidence-dir PATH")


def main() -> int:
    evidence = _evidence_argument()
    profile = Path(tempfile.mkdtemp(prefix="birkin-terminal-pty-"))
    try:
        scenario = run_terminal_scenario(profile)
    except (AssertionError, OSError, pexpect.ExceptionPexpect) as exc:
        try:
            shutil.rmtree(profile)
        except OSError as cleanup_exc:
            print(f"terminal QA failed; cleanup failed: {cleanup_exc}")
            return 1
        print(f"terminal QA failed: {exc}")
        return 1

    result = emit_terminal_evidence(
        EvidenceInputs(evidence=evidence, profile=profile, scenario=scenario)
    )
    if not result.ok:
        print(f"terminal QA failed: {result.reason}")
        return 1
    try:
        verify_evidence(evidence)
    except EvidenceError as exc:
        print(f"terminal QA failed: {exc}")
        return 1
    print("PTY workspace QA passed: approval/resize/Unicode/interrupt/reconnect/cleanup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
