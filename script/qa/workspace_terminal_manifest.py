"""Exact typed manifest contract for portable terminal evidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import ClassVar, Literal, final

from pydantic import BaseModel, ConfigDict
from typing_extensions import override

WIDTHS = (60, 80, 100, 120, 160)


@final
class ArtifactKind(str, Enum):
    REAL_PTY = "real_pty"
    SEMANTIC_SVG = "semantic_svg"
    BROWSER_SCREENSHOT = "browser_screenshot"


class ArtifactRecord(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    path: str
    kind: ArtifactKind
    sha256: str
    bytes: int


class ChildRecord(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    pid: int
    exit_code: int | None
    exited: bool


class CleanupRecord(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    children: tuple[ChildRecord, ...]
    profile_removed: bool
    reason: str | None


class EvidenceManifest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    status: Literal["PASS", "FAIL"]
    reason: str | None
    artifacts: tuple[ArtifactRecord, ...]
    cleanup: CleanupRecord


@dataclass(frozen=True, slots=True)
class EvidenceError(Exception):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


def artifact_record(path: Path, kind: ArtifactKind) -> ArtifactRecord:
    return ArtifactRecord(
        path=path.name,
        kind=kind,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        bytes=path.stat().st_size,
    )


def register_browser_screenshot(evidence: Path, screenshot: Path) -> None:
    """Add the one contract browser PNG to verified core evidence."""
    if screenshot.resolve() != (evidence / "terminal.png").resolve():
        raise EvidenceError(f"unexpected artifact path: {screenshot.name}")
    verify_evidence(evidence)
    if screenshot.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        raise EvidenceError("browser screenshot is not a PNG")
    manifest_path = evidence / "manifest.json"
    manifest = EvidenceManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    screenshot_record = artifact_record(
        screenshot,
        ArtifactKind.BROWSER_SCREENSHOT,
    )
    updated = manifest.model_copy(
        update={"artifacts": (*manifest.artifacts, screenshot_record)}
    )
    _ = manifest_path.write_text(
        updated.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def verify_evidence(evidence: Path, *, require_browser: bool = False) -> None:
    """Require the exact unique artifact contract and verify every digest."""
    manifest = EvidenceManifest.model_validate_json(
        (evidence / "manifest.json").read_text(encoding="utf-8")
    )
    if manifest.status != "PASS":
        raise EvidenceError(manifest.reason or "terminal evidence failed")
    if not manifest.cleanup.profile_removed:
        raise EvidenceError(manifest.cleanup.reason or "profile cleanup failed")
    if any(not child.exited for child in manifest.cleanup.children):
        raise EvidenceError("live child remains")

    expected = {
        "terminal-pty.raw.txt": ArtifactKind.REAL_PTY,
        "terminal-pty.json": ArtifactKind.REAL_PTY,
        **{
            f"terminal-{width}.svg": ArtifactKind.SEMANTIC_SVG
            for width in WIDTHS
        },
    }
    if require_browser:
        expected["terminal.png"] = ArtifactKind.BROWSER_SCREENSHOT
    seen: set[str] = set()
    for artifact in manifest.artifacts:
        if artifact.path in seen:
            raise EvidenceError(f"duplicate artifact: {artifact.path}")
        seen.add(artifact.path)
        expected_kind = expected.get(artifact.path)
        if expected_kind is None:
            raise EvidenceError(f"unexpected artifact path: {artifact.path}")
        if artifact.kind is not expected_kind:
            raise EvidenceError(f"kind mismatch: {artifact.path}")
        path = evidence / artifact.path
        if not path.exists():
            raise EvidenceError(f"missing artifact: {artifact.path}")
        if path.stat().st_size == 0:
            raise EvidenceError(f"empty artifact: {artifact.path}")
        if path.stat().st_size != artifact.bytes:
            raise EvidenceError(f"size mismatch: {artifact.path}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != artifact.sha256:
            raise EvidenceError(f"digest mismatch: {artifact.path}")
    for name in expected:
        if name not in seen:
            raise EvidenceError(f"missing manifest artifact: {name}")
