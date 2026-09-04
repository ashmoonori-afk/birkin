from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

if importlib.util.find_spec("pexpect") is None:
    pytest.skip("pexpect is not installed", allow_module_level=True)

from script.qa.workspace_terminal_evidence import (  # noqa: E402
    ArtifactKind,
    EvidenceError,
    EvidenceInputs,
    EvidenceManifest,
    emit_terminal_evidence,
    register_browser_screenshot,
    verify_evidence,
)
from script.qa.workspace_terminal_pty import (  # noqa: E402
    ChildExit,
    TerminalCapture,
    TerminalObservations,
    TerminalScenario,
)


def _scenario(widths: tuple[int, ...] = (60, 80, 100, 120, 160)) -> TerminalScenario:
    return TerminalScenario(
        transcript="opaque terminal output",
        captures=tuple(
            TerminalCapture(width=width, raw=f"capture-{width}")
            for width in widths
        ),
        children=(ChildExit(pid=101, exit_code=0), ChildExit(pid=202, exit_code=0)),
        observations=TerminalObservations(
            approval=True,
            unicode_paste=True,
            interrupt=True,
            reconnect=True,
        ),
        first_port=7001,
        reconnect_port=7002,
    )


def _emit(tmp_path: Path) -> Path:
    evidence = tmp_path / "evidence"
    profile = tmp_path / "profile"
    profile.mkdir()
    result = emit_terminal_evidence(
        EvidenceInputs(evidence=evidence, profile=profile, scenario=_scenario())
    )
    assert result.ok
    return evidence


def _manifest(evidence: Path) -> EvidenceManifest:
    return EvidenceManifest.model_validate_json(
        (evidence / "manifest.json").read_text(encoding="utf-8")
    )


def _rewrite_manifest(evidence: Path, manifest: EvidenceManifest) -> None:
    _ = (evidence / "manifest.json").write_text(
        manifest.model_dump_json(),
        encoding="utf-8",
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
    manifest = _manifest(evidence)
    artifacts = {item.path: item for item in manifest.artifacts}
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
    assert artifacts["terminal-pty.raw.txt"].kind is ArtifactKind.REAL_PTY
    assert artifacts["terminal-120.svg"].kind is ArtifactKind.SEMANTIC_SVG
    assert artifacts["terminal-120.svg"].sha256 == hashlib.sha256(
        (evidence / "terminal-120.svg").read_bytes()
    ).hexdigest()
    metadata_text = (evidence / "terminal-pty.json").read_text(encoding="utf-8")
    assert '"approval": true' in metadata_text
    assert '"unicode_paste": true' in metadata_text
    assert '"interrupt": true' in metadata_text
    assert '"reconnect": true' in metadata_text
    assert manifest.cleanup.model_dump(mode="json") == {
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
    manifest = _manifest(evidence)
    assert not result.ok
    assert result.reason == "profile cleanup failed: profile locked"
    assert manifest.cleanup.profile_removed is False
    assert manifest.cleanup.reason == result.reason


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
        observations=scenario.observations,
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


def test_verifier_rejects_truncated_pass_manifest(tmp_path: Path) -> None:
    # Given: a PASS manifest with one required SVG entry removed.
    evidence = _emit(tmp_path)
    manifest = _manifest(evidence)
    truncated = manifest.model_copy(
        update={
            "artifacts": tuple(
                artifact
                for artifact in manifest.artifacts
                if artifact.path != "terminal-120.svg"
            )
        }
    )
    _rewrite_manifest(evidence, truncated)

    # When / Then: exact-set verification rejects the truncated claim.
    with pytest.raises(EvidenceError, match="missing manifest artifact: terminal-120.svg"):
        verify_evidence(evidence)


def test_verifier_rejects_duplicate_and_wrong_kind_entries(tmp_path: Path) -> None:
    # Given: required entries plus a duplicate whose kind is also wrong.
    evidence = _emit(tmp_path)
    manifest = _manifest(evidence)
    duplicate = manifest.artifacts[0].model_copy(
        update={"kind": ArtifactKind.SEMANTIC_SVG}
    )
    duplicated = manifest.model_copy(
        update={"artifacts": (*manifest.artifacts, duplicate)}
    )
    _rewrite_manifest(evidence, duplicated)

    # When / Then: duplicate identity is rejected before trusting kind/digest.
    with pytest.raises(EvidenceError, match="duplicate artifact: terminal-pty.raw.txt"):
        verify_evidence(evidence)


def test_verifier_rejects_wrong_kind_and_wrong_path(tmp_path: Path) -> None:
    # Given: a core artifact with an invalid kind and then an unexpected path.
    evidence = _emit(tmp_path)
    manifest = _manifest(evidence)
    wrong_kind = manifest.artifacts[0].model_copy(
        update={"kind": ArtifactKind.SEMANTIC_SVG}
    )
    _rewrite_manifest(
        evidence,
        manifest.model_copy(
            update={"artifacts": (wrong_kind, *manifest.artifacts[1:])}
        ),
    )

    # When / Then: kind mismatch is rejected.
    with pytest.raises(EvidenceError, match="kind mismatch: terminal-pty.raw.txt"):
        verify_evidence(evidence)

    wrong_path = manifest.artifacts[0].model_copy(
        update={"path": "../terminal-pty.raw.txt"}
    )
    _rewrite_manifest(
        evidence,
        manifest.model_copy(
            update={"artifacts": (wrong_path, *manifest.artifacts[1:])}
        ),
    )
    with pytest.raises(EvidenceError, match="unexpected artifact path"):
        verify_evidence(evidence)


def test_verifier_rejects_digest_tamper(tmp_path: Path) -> None:
    # Given: emitted evidence whose transcript bytes changed after hashing.
    evidence = _emit(tmp_path)
    transcript = evidence / "terminal-pty.raw.txt"
    payload = transcript.read_bytes()
    _ = transcript.write_bytes(bytes([payload[0] ^ 1]) + payload[1:])

    # When / Then: equal-length tampering fails the digest check.
    with pytest.raises(EvidenceError, match="digest mismatch: terminal-pty.raw.txt"):
        verify_evidence(evidence)


def test_browser_contract_requires_exactly_one_terminal_png(tmp_path: Path) -> None:
    # Given: a valid core manifest and one browser PNG.
    evidence = _emit(tmp_path)
    screenshot = evidence / "terminal.png"
    _ = screenshot.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    register_browser_screenshot(evidence, screenshot)
    verify_evidence(evidence, require_browser=True)
    manifest = _manifest(evidence)
    duplicated = manifest.model_copy(
        update={"artifacts": (*manifest.artifacts, manifest.artifacts[-1])}
    )
    _rewrite_manifest(evidence, duplicated)

    # When / Then: duplicate browser evidence is rejected.
    with pytest.raises(EvidenceError, match="duplicate artifact: terminal.png"):
        verify_evidence(evidence, require_browser=True)


def test_browser_registration_rejects_wrong_path(tmp_path: Path) -> None:
    # Given: valid core evidence and a PNG with a non-contract filename.
    evidence = _emit(tmp_path)
    screenshot = evidence / "other.png"
    _ = screenshot.write_bytes(b"\x89PNG\r\n\x1a\nfixture")

    # When / Then: registration cannot expand the artifact namespace.
    with pytest.raises(EvidenceError, match="unexpected artifact path: other.png"):
        register_browser_screenshot(evidence, screenshot)
