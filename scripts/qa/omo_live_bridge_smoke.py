# /// script
# requires-python = ">=3.10"
# ///
"""Exercise Birkin's live bridge against isolated real OMO processes."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from unittest.mock import patch

from birkin.omo_live import OmoLiveClient
from scripts.qa.omo_live_harness import (
    OmoHarness,
    OmoHarnessConfig,
    start_omo,
)


@dataclass(frozen=True, slots=True)
class QaArgs:
    omo: Path
    sessions: tuple[str, ...]
    message: str
    evidence_dir: Path


def parse_args() -> QaArgs:
    parser = argparse.ArgumentParser(
        description="Run the Birkin live OMO bridge process smoke test."
    )
    _ = parser.add_argument("--omo", required=True, type=Path)
    _ = parser.add_argument("--session", action="append", required=True)
    _ = parser.add_argument("--message", required=True)
    _ = parser.add_argument("--evidence-dir", required=True, type=Path)
    parsed = parser.parse_args()
    return QaArgs(
        omo=cast(Path, parsed.omo),
        sessions=tuple(cast(list[str], parsed.session)),
        message=cast(str, parsed.message),
        evidence_dir=cast(Path, parsed.evidence_dir),
    )


def _lock_paths(root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(str(path.relative_to(root)) for path in root.rglob("settings.json.lock"))
    )


def run(args: QaArgs) -> Path:
    sessions = tuple(dict.fromkeys(args.sessions))
    if len(sessions) != 2:
        raise ValueError("The smoke test requires exactly two distinct --session IDs.")
    omo = args.omo.resolve()
    if not omo.is_file():
        raise FileNotFoundError(omo)
    evidence_dir = args.evidence_dir
    evidence_dir.mkdir(parents=True, exist_ok=True)
    temp_path: Path
    harnesses: list[OmoHarness] = []
    artifact: Path

    try:
        with tempfile.TemporaryDirectory(prefix="birkin-omo-bridge-qa-") as temporary:
            temp_path = Path(temporary)
            registry = temp_path / "registry"
            historical = temp_path / "historical" / "historical-session.jsonl"
            historical.parent.mkdir(parents=True)
            historical_payload = (
                b'{"id":"historical-session","version":1}\n'
                b'{"type":"message","role":"user","content":"leave unchanged"}\n'
            )
            _ = historical.write_bytes(historical_payload)
            historical_mtime = historical.stat().st_mtime_ns
            harness_config = OmoHarnessConfig(omo, temp_path, registry)
            harnesses = [
                start_omo(harness_config, session_id)
                for session_id in sessions
            ]
            ready = [
                harness.wait_event("ready", timeout=20)
                for harness in harnesses
            ]
            locks_before = _lock_paths(temp_path)
            client = OmoLiveClient((registry,), timeout=5)
            with patch(
                "subprocess.Popen",
                side_effect=AssertionError(
                    "Birkin attempted to start a replacement OMO process."
                ),
            ):
                acknowledgements = client.send_to_sessions(sessions, args.message)
                replay_acknowledgements = tuple(
                    client.send_to_session(
                        ack.session_id,
                        args.message,
                        request_id=ack.request_id,
                    )
                    for ack in acknowledgements
                )
            deliveries = [
                harness.wait_event("delivery", timeout=10)
                for harness in harnesses
            ]
            duplicates = sum(
                len(harness.delivery_events()) for harness in harnesses
            )
            locks_after = _lock_paths(temp_path)
            resolved_ids = tuple(str(event.get("session_id")) for event in ready)
            acknowledged_ids = tuple(ack.session_id for ack in acknowledgements)
            delivered_ids = tuple(
                str(event.get("session_id")) for event in deliveries
            )
            historical_changed = (
                historical.read_bytes() != historical_payload
                or historical.stat().st_mtime_ns != historical_mtime
            )
            if resolved_ids != sessions:
                raise AssertionError("The bridge resolved sessions outside the exact IDs.")
            if acknowledged_ids != sessions or delivered_ids != sessions:
                raise AssertionError("Acknowledgement identity did not match exact targets.")
            if duplicates != 0:
                raise AssertionError("A live OMO session received duplicate input.")
            if locks_after != locks_before:
                raise AssertionError("Birkin changed an OMO settings lock.")
            if historical_changed:
                raise AssertionError("Birkin changed an unrelated historical session.")
            if any(event.get("message") != args.message for event in deliveries):
                raise AssertionError("A live OMO session received the wrong message.")
            if any(event.get("delivery_count") != 1 for event in deliveries):
                raise AssertionError("A live OMO session delivery was not exactly once.")
            if any(not ack.replayed for ack in replay_acknowledgements):
                raise AssertionError("A replay was not acknowledged as deduplicated.")

            artifact = evidence_dir / "omo-live-bridge-smoke.json"
            payload = {
                "scenario": "exact live OMO session delivery",
                "message": args.message,
                "requested_session_ids": list(sessions),
                "resolved_session_ids": list(resolved_ids),
                "ready": ready,
                "acknowledgements": [
                    {
                        "session_id": ack.session_id,
                        "request_id": ack.request_id,
                        "accepted": ack.accepted,
                        "replayed": ack.replayed,
                    }
                    for ack in acknowledgements
                ],
                "replay_acknowledgements": [
                    {
                        "session_id": ack.session_id,
                        "request_id": ack.request_id,
                        "accepted": ack.accepted,
                        "replayed": ack.replayed,
                    }
                    for ack in replay_acknowledgements
                ],
                "deliveries": deliveries,
                "duplicate_deliveries": duplicates,
                "unrelated_deliveries": 0,
                "historical_sessions_checked": ["historical-session"],
                "historical_sessions_changed": int(historical_changed),
                "replacement_processes_started_by_birkin": 0,
                "settings_locks_changed_by_birkin": False,
                "initial_omo_pids": [harness.process.pid for harness in harnesses],
            }
            _ = artifact.write_text(
                f"{json.dumps(payload, indent=2, sort_keys=True)}\n",
                encoding="utf-8",
            )
            client.close()
    finally:
        for harness in harnesses:
            harness.close()

    if not artifact.is_file():
        raise AssertionError("The smoke test did not write its evidence artifact.")
    if temp_path.exists():
        raise AssertionError("The smoke test did not remove its temporary state.")
    return artifact


def main() -> int:
    args = parse_args()
    try:
        artifact = run(args)
    except (
        AssertionError,
        json.JSONDecodeError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ) as exc:
        _ = sys.stderr.write(f"OMO live bridge smoke failed: {exc}\n")
        return 1
    _ = sys.stdout.write(f"PASS artifact={artifact}\n")
    _ = sys.stdout.write(
        "cleanup: real OMO processes stopped; temporary state removed\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
