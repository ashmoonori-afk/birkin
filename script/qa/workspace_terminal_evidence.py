"""Artifact emission and cleanup contract for portable terminal QA."""

from __future__ import annotations

import html
import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from script.qa.workspace_terminal_manifest import (
    ArtifactKind,
    ArtifactRecord,
    ChildRecord,
    CleanupRecord,
    EvidenceError,
    EvidenceManifest,
    WIDTHS,
    artifact_record,
    register_browser_screenshot,
    verify_evidence,
)
from script.qa.workspace_terminal_pty import TerminalScenario


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
    for name in (
        "manifest.json",
        "terminal-pty.raw.txt",
        "terminal-pty.json",
        "terminal.png",
        *(f"terminal-{width}.svg" for width in WIDTHS),
    ):
        (inputs.evidence / name).unlink(missing_ok=True)
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
        "approval": inputs.scenario.observations.approval,
        "unicode_paste": inputs.scenario.observations.unicode_paste,
        "interrupt": inputs.scenario.observations.interrupt,
        "reconnect": inputs.scenario.observations.reconnect,
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
        artifact_record(
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


__all__ = [
    "ArtifactKind",
    "ArtifactRecord",
    "EvidenceError",
    "EvidenceInputs",
    "EvidenceManifest",
    "EvidenceResult",
    "emit_terminal_evidence",
    "register_browser_screenshot",
    "verify_evidence",
]
