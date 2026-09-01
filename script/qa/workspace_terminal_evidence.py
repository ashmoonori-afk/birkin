"""Typed artifact and cleanup contract for portable terminal QA."""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, override

from pydantic import BaseModel, ConfigDict

from script.qa.workspace_terminal_pty import TerminalScenario

WIDTHS: Final = (60, 80, 100, 120, 160)


class ArtifactKind(StrEnum):
    REAL_PTY = "real_pty"
    SEMANTIC_SVG = "semantic_svg"
    BROWSER_SCREENSHOT = "browser_screenshot"


class ArtifactRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    kind: ArtifactKind
    sha256: str
    bytes: int


class ChildRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    pid: int
    exit_code: int | None
    exited: bool


class CleanupRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    children: tuple[ChildRecord, ...]
    profile_removed: bool
    reason: str | None


class EvidenceManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    reason: str | None
    artifacts: tuple[ArtifactRecord, ...]
    cleanup: CleanupRecord


@dataclass(frozen=True, slots=True)
class EvidenceInputs:
    evidence: Path
    profile: Path
    scenario: TerminalScenario


@dataclass(frozen=True, slots=True)
class EvidenceResult:
    ok: bool
    reason: str | None
    exit_code: int


@dataclass(frozen=True, slots=True)
class EvidenceError(Exception):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(path: Path, kind: ArtifactKind) -> ArtifactRecord:
    return ArtifactRecord(
        path=path.name,
        kind=kind,
        sha256=_sha256(path),
        bytes=path.stat().st_size,
    )


def _write_terminal_svg(path: Path, raw: str, columns: int) -> None:
    cleaned = re.sub(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|[=>])", "", raw)
    lines = [line.replace("\r", "") for line in cleaned.splitlines() if line.strip()][-24:]
    spans = "".join(
        f'<tspan x="12" dy="18">{html.escape(line)}</tspan>' for line in lines
    )
    width = columns * 9 + 24
    height = len(lines) * 18 + 24
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">'
        '<rect width="100%" height="100%" fill="#11100f"/>'
        '<text x="12" y="4" fill="#f4eadf" '
        'font-family="ui-monospace, monospace" font-size="14">'
        f"{spans}</text></svg>\n"
    )
    _ = path.write_text(svg, encoding="utf-8")


def _first_artifact_error(evidence: Path) -> str | None:
    expected = [
        "terminal-pty.raw.txt",
        "terminal-pty.json",
        *(f"terminal-{width}.svg" for width in WIDTHS),
    ]
    for name in expected:
        path = evidence / name
        if not path.exists():
            return f"missing artifact: {name}"
        if path.stat().st_size == 0:
            return f"empty artifact: {name}"
    return None


def emit_terminal_evidence(
    inputs: EvidenceInputs,
    *,
    remove_profile: Callable[[Path], None] = shutil.rmtree,
) -> EvidenceResult:
    """Write all scenario evidence, perform cleanup, and retain failures."""
    inputs.evidence.mkdir(parents=True, exist_ok=True)
    transcript = inputs.evidence / "terminal-pty.raw.txt"
    _ = transcript.write_text(inputs.scenario.transcript, encoding="utf-8")
    captures = {capture.width: capture.raw for capture in inputs.scenario.captures}
    for width in WIDTHS:
        raw = captures.get(width)
        if raw is not None:
            _write_terminal_svg(inputs.evidence / f"terminal-{width}.svg", raw, width)

    metadata = {
        "ports": [inputs.scenario.first_port, inputs.scenario.reconnect_port],
        "widths": sorted(captures),
        "children": [
            {"pid": child.pid, "exit_code": child.exit_code}
            for child in inputs.scenario.children
        ],
        "approval": "Approval required" in inputs.scenario.transcript,
        "unicode_paste": "붙여넣기-" in inputs.scenario.transcript,
        "interrupt": "Interrupted safely" in inputs.scenario.transcript,
        "reconnect": "--- RECONNECT ---" in inputs.scenario.transcript,
    }
    metadata_path = inputs.evidence / "terminal-pty.json"
    _ = metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    cleanup_reason = None
    try:
        remove_profile(inputs.profile)
        profile_removed = True
    except OSError as exc:
        profile_removed = False
        cleanup_reason = f"profile cleanup failed: {exc}"

    children = tuple(
        ChildRecord(
            pid=child.pid,
            exit_code=child.exit_code,
            exited=child.exit_code is not None,
        )
        for child in inputs.scenario.children
    )
    child_reason = next(
        (
            f"child process {child.pid} did not exit"
            for child in inputs.scenario.children
            if child.exit_code is None
        ),
        None,
    )
    artifact_reason = _first_artifact_error(inputs.evidence)
    reason = artifact_reason or child_reason or cleanup_reason
    paths = [transcript, metadata_path]
    paths.extend(
        inputs.evidence / f"terminal-{width}.svg"
        for width in WIDTHS
        if (inputs.evidence / f"terminal-{width}.svg").is_file()
    )
    artifacts = tuple(
        _artifact(
            path,
            ArtifactKind.SEMANTIC_SVG if path.suffix == ".svg" else ArtifactKind.REAL_PTY,
        )
        for path in paths
    )
    manifest = EvidenceManifest(
        status="PASS" if reason is None else "FAIL",
        reason=reason,
        artifacts=artifacts,
        cleanup=CleanupRecord(
            children=children,
            profile_removed=profile_removed,
            reason=cleanup_reason,
        ),
    )
    _ = (inputs.evidence / "manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return EvidenceResult(
        ok=reason is None,
        reason=reason,
        exit_code=0 if reason is None else 1,
    )


def register_browser_screenshot(evidence: Path, screenshot: Path) -> None:
    """Add one browser-rendered PNG to an existing verified manifest."""
    if screenshot.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        raise EvidenceError("browser screenshot is not a PNG")
    manifest_path = evidence / "manifest.json"
    manifest = EvidenceManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    screenshot_record = _artifact(screenshot, ArtifactKind.BROWSER_SCREENSHOT)
    updated = manifest.model_copy(
        update={"artifacts": (*manifest.artifacts, screenshot_record)}
    )
    _ = manifest_path.write_text(updated.model_dump_json(indent=2) + "\n", encoding="utf-8")


def verify_evidence(evidence: Path, *, require_browser: bool = False) -> None:
    """Reject the first absent, empty, kind-invalid, or digest-invalid artifact."""
    manifest = EvidenceManifest.model_validate_json(
        (evidence / "manifest.json").read_text(encoding="utf-8")
    )
    if manifest.status != "PASS":
        raise EvidenceError(manifest.reason or "terminal evidence failed")
    if not manifest.cleanup.profile_removed:
        raise EvidenceError(manifest.cleanup.reason or "profile cleanup failed")
    if any(not child.exited for child in manifest.cleanup.children):
        raise EvidenceError("live child remains")
    if require_browser and not any(
        artifact.kind is ArtifactKind.BROWSER_SCREENSHOT for artifact in manifest.artifacts
    ):
        raise EvidenceError("missing artifact: terminal.png")
    for artifact in manifest.artifacts:
        path = evidence / artifact.path
        if not path.exists():
            raise EvidenceError(f"missing artifact: {artifact.path}")
        if path.stat().st_size == 0:
            raise EvidenceError(f"empty artifact: {artifact.path}")
        if _sha256(path) != artifact.sha256:
            raise EvidenceError(f"digest mismatch: {artifact.path}")
        if path.suffix == ".svg" and artifact.kind is not ArtifactKind.SEMANTIC_SVG:
            raise EvidenceError(f"kind mismatch: {artifact.path}")
