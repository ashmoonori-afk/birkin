#!/usr/bin/env python3
"""Run one existing-account provider completion without changing credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from birkin import config
from birkin.runtime import build_session

MARKER = "NATIVE_PROVIDER_PROBE_OK"
PROMPT = f"Reply with exactly {MARKER} and no other text."


def run_probe(*, provider: str, model: str) -> tuple[dict[str, object], int]:
    cfg: dict[str, Any] = dict(config.load_config())
    cfg.update({
        "provider": provider,
        "model": model,
        "auto_approve": [],
        "self_improve": False,
        "checkpoints": False,
        "evidence_gate_enabled": False,
        "session_goal_fallback": False,
        "session_id": "native-provider-probe",
        "max_turns": 1,
    })
    reply = ""
    error_type: str | None = None
    session = None
    try:
        session = build_session(cfg)
        reply = session.ask(
            PROMPT,
            review_skills=False,
            record_turn=False,
        ).strip()
    except Exception as error:  # noqa: BLE001 - evidence boundary
        error_type = type(error).__name__
    finally:
        if session is not None:
            session.close()
    succeeded = error_type is None and reply == MARKER
    record: dict[str, object] = {
        "provider": provider,
        "model": model,
        "marker": MARKER,
        "reply_bytes": len(reply.encode()),
        "reply_sha256": hashlib.sha256(reply.encode()).hexdigest(),
        "status": "pass" if succeeded else "fail",
    }
    if error_type is not None:
        record["error_type"] = error_type
    return record, 0 if succeeded else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="codex-cli", choices=("codex-cli",))
    parser.add_argument("--model", default="default")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    record, status = run_probe(provider=args.provider, model=args.model)
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"))
    print(encoded)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
