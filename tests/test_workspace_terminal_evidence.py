from __future__ import annotations

import hashlib
import json
from pathlib import Path

from script.qa.workspace_terminal_evidence import (
    EvidenceError,
    EvidenceInputs,
    emit_terminal_evidence,
    verify_evidence,
)
from script.qa.workspace_terminal_pty import (
    ChildExit,
    TerminalCapture,
    TerminalScenario,
)


def _scenario(widths: tuple[int, ...] = (60, 80, 100, 120, 160)) -> TerminalScenario:
    return TerminalScenario(
        transcript="approval\n한글-🧵\nInterrupted safely\nreconnect",
        captures=tuple(
            TerminalCapture(width=width, raw=f"capture-{width}")
            for width in widths
        ),
        children=(ChildExit(pid=101, exit_code=0), ChildExit(pid=202, exit_code=0)),
        first_port=7001,
        reconnect_port=7002,
    )


def test_evidence_manifest_records_typed_kinds_digests_and_cleanup(
    tmp_path: Path,
) -> None:
    # Given: one complete shared terminal scenario and a removable profile.
    evidence = tmp_path / "evidence"
    profile = tmp_path / "profile"
    profile.mkdir()

    # When: the evidence contract emits and verifies the artifacts.
    result = emit_terminal_evidence(
        EvidenceInputs(evidence=evidence, profile=profile, scenario=_scenario()),
    )
    verify_evidence(evidence)

    # Then: five semantic captures and exact child/profile cleanup are proven.
    manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
    artifacts = {item["path"]: item for item in manifest["artifacts"]}
    assert result.ok
    assert result.exit_code == 0
    assert set(artifacts) == {
        "terminal-pty.raw.txt",
        "terminal-pty.json",
        "terminal-60.svg",
        "terminal-80.svg",
        "terminal-100.svg",
        "terminal-120.svg",
        "terminal-160.svg",
    }
    assert artifacts["terminal-pty.raw.txt"]["kind"] == "real_pty"
    assert artifacts["terminal-120.svg"]["kind"] == "semantic_svg"
    assert artifacts["terminal-120.svg"]["sha256"] == hashlib.sha256(
        (evidence / "terminal-120.svg").read_bytes()
    ).hexdigest()
    assert manifest["cleanup"] == {
        "children": [
            {"pid": 101, "exit_code": 0, "exited": True},
            {"pid": 202, "exit_code": 0, "exited": True},
        ],
        "profile_removed": True,
        "reason": None,
    }
    assert not profile.exists()


def test_incomplete_capture_set_fails_and_names_first_artifact(tmp_path: Path) -> None:
    # Given: an injected driver result missing the 120-column capture.
    profile = tmp_path / "profile"
    profile.mkdir()

    # When: the evidence contract evaluates the incomplete result.
    result = emit_terminal_evidence(
        EvidenceInputs(
            evidence=tmp_path / "evidence",
            profile=profile,
            scenario=_scenario((60, 80, 100, 160)),
        ),
    )

    # Then: it fails nonzero semantics with the first missing artifact named.
    assert not result.ok
    assert result.exit_code == 1
    assert result.reason == "missing artifact: terminal-120.svg"


def test_cleanup_failure_is_nonzero_and_retains_reasoned_manifest(
    tmp_path: Path,
) -> None:
    # Given: a complete scenario whose profile deletion fails.
    evidence = tmp_path / "evidence"
    profile = tmp_path / "profile"
    profile.mkdir()

    def fail_remove(_path: Path) -> None:
        raise OSError("profile locked")

    # When: cleanup is attempted through the injected remover.
    result = emit_terminal_evidence(
        EvidenceInputs(evidence=evidence, profile=profile, scenario=_scenario()),
        remove_profile=fail_remove,
    )

    # Then: failure is explicit and the manifest retains its cleanup reason.
    manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
    assert not result.ok
    assert result.reason == "profile cleanup failed: profile locked"
    assert manifest["cleanup"]["profile_removed"] is False
    assert manifest["cleanup"]["reason"] == result.reason


def test_live_child_injection_fails_nonzero_and_names_child(tmp_path: Path) -> None:
    # Given: a complete artifact set with one child lacking an exit status.
    evidence = tmp_path / "evidence"
    profile = tmp_path / "profile"
    profile.mkdir()
    scenario = _scenario()
    live_child = TerminalScenario(
        transcript=scenario.transcript,
        captures=scenario.captures,
        children=(scenario.children[0], ChildExit(pid=303, exit_code=None)),
        first_port=scenario.first_port,
        reconnect_port=scenario.reconnect_port,
    )

    # When: the cleanup contract evaluates the injected live child handle.
    result = emit_terminal_evidence(
        EvidenceInputs(evidence=evidence, profile=profile, scenario=live_child)
    )

    # Then: orchestration fails nonzero and records the exact child.
    assert result.exit_code == 1
    assert result.reason == "child process 303 did not exit"


def test_verifier_rejects_partial_artifact_after_emission(tmp_path: Path) -> None:
    # Given: valid emitted evidence with one artifact removed afterward.
    evidence = tmp_path / "evidence"
    profile = tmp_path / "profile"
    profile.mkdir()
    result = emit_terminal_evidence(
        EvidenceInputs(evidence=evidence, profile=profile, scenario=_scenario()),
    )
    assert result.ok
    (evidence / "terminal-120.svg").unlink()

    # When: manifest verification checks the artifact set.
    try:
        verify_evidence(evidence)
    except EvidenceError as exc:
        diagnostic = str(exc)
    else:
        diagnostic = "verification unexpectedly passed"

    # Then: the absent artifact is the exact failure.
    assert diagnostic == "missing artifact: terminal-120.svg"
