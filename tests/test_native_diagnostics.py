from __future__ import annotations

import os
import stat
from pathlib import Path

from birkin.native.diagnostics import DiagnosticRing


def _record(ring: DiagnosticRing, *, attempt: int, detail: str = "") -> None:
    ring.record(
        transport="uds",
        state="disconnected",
        error_code="E_TEST",
        attempt=attempt,
        last_cursor=7,
        instance_id="instance-1",
        server_version="1.0.0",
        client_version="1.0.0",
        detail=detail,
    )


def test_diagnostics_ring_is_bounded_and_ordered() -> None:
    ring = DiagnosticRing(capacity=2)
    _record(ring, attempt=1)
    _record(ring, attempt=2)
    _record(ring, attempt=3)

    entries = ring.entries()

    assert [entry["attempt"] for entry in entries] == [2, 3]


def test_diagnostics_redact_secrets_tracebacks_and_long_details() -> None:
    secret = "seeded-diagnostic-secret"
    ring = DiagnosticRing(capacity=2)
    _record(
        ring,
        attempt=1,
        detail="\n".join(
            (
                "Traceback (most recent call last):",
                f"RuntimeError: token={secret}",
                "x" * 500,
            )
        ),
    )

    rendered = ring.to_json()

    assert secret not in rendered
    assert "Traceback" not in rendered
    assert len(str(ring.entries()[0]["detail"])) <= 300


def test_diagnostics_export_is_private_without_capabilities(
    tmp_path: Path,
) -> None:
    ring = DiagnosticRing(capacity=2)
    _record(ring, attempt=1, detail="safe")
    destination = tmp_path / "diagnostics.json"

    ring.export(destination)

    exported = destination.read_text(encoding="utf-8")
    assert "capability" not in exported
    assert "bootstrap_secret" not in exported
    if os.name != "nt":
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_diagnostics_export_redacts_seeded_bearer_secret(
    tmp_path: Path,
) -> None:
    ring = DiagnosticRing(capacity=2)
    _record(
        ring,
        attempt=1,
        detail="request failed: Bearer SEEDED_PUBLIC_SECRET",
    )
    destination = tmp_path / "diagnostics.json"

    ring.export(destination)

    exported = destination.read_text(encoding="utf-8")
    assert "SEEDED_PUBLIC_SECRET" not in exported
    assert "[REDACTED]" in exported
