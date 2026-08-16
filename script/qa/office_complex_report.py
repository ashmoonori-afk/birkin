"""Bounded stdout and full-file evidence for complex Office dogfood."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast


def _status(value: object) -> str:
    if not isinstance(value, Mapping):
        return "recorded"
    mapping = cast(Mapping[object, object], value)
    status = mapping.get("status")
    if isinstance(status, str):
        return status
    if isinstance(mapping.get("error"), Mapping):
        return "refused"
    return "recorded"


def _format_summary(evidence: dict[str, object]) -> dict[str, object]:
    operations = cast(dict[str, object], evidence["operations"])
    before = cast(str, evidence["source_sha256_before"])
    after = cast(str, evidence["source_sha256_after"])
    return {
        "artifact_hashes": evidence.get("artifact_hashes", []),
        "expected_content_match": evidence.get("expected_content_match"),
        "operations": {
            name: _status(value) for name, value in sorted(operations.items())
        },
        "reopen_validation": evidence.get("reopen_validation"),
        "source_preserved": before == after,
        "source_sha256_after": after,
        "source_sha256_before": before,
    }


def write_bounded_report(
    report: dict[str, object],
    output_dir: Path,
) -> dict[str, object]:
    """Persist complete evidence and return a bounded machine summary."""
    serialized = json.dumps(
        report,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    full_path = output_dir / "complex-dogfood-report.json"
    _ = full_path.write_bytes(serialized)

    formats = cast(dict[str, dict[str, object]], report["formats"])
    unsupported = cast(dict[str, dict[str, object]], report["unsupported_identities"])
    legacy = cast(dict[str, dict[str, object]], report["legacy"])
    return {
        "cleanup_receipt": report["cleanup_receipt"],
        "expected_refusal_count": len(
            cast(list[object], report["expected_refusals"])
        ),
        "formats": {
            name: _format_summary(evidence)
            for name, evidence in sorted(formats.items())
        },
        "full_report": {
            "bytes": len(serialized),
            "sha256": hashlib.sha256(serialized).hexdigest(),
            "uri": str(full_path),
        },
        "jail": report["jail"],
        "legacy": {
            name: _status(evidence.get("conversion"))
            for name, evidence in sorted(legacy.items())
        },
        "ok": report["ok"],
        "tools_exercised": report["tools_exercised"],
        "unsupported_identities": {
            name: _status(evidence)
            for name, evidence in sorted(unsupported.items())
        },
    }
