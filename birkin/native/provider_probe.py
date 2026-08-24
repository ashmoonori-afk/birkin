"""Existing-account provider proof for native release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from birkin import config
from birkin.bundled_browser import ensure_bundled_browser
from birkin.runtime import build_session

MARKER = "NATIVE_PROVIDER_PROBE_OK"
PROMPT = f"Reply with exactly {MARKER} and no other text."


def run_probe(
    *,
    provider: str,
    model: str,
    artifact_path: Path | None = None,
) -> tuple[dict[str, object], int]:
    """Run one real completion and return bounded, non-secret evidence."""
    cfg = config.load_config()
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
    browser_runtime: Path | None = None
    resolved_provider = provider
    resolved_model = model
    route = "cli" if provider in config.CLI_PROVIDERS else "unknown"
    cwd = Path.cwd().resolve()
    session = None
    try:
        browser_runtime = ensure_bundled_browser()
        session = build_session(cfg)
        resolved_provider = str(getattr(session.client, "provider", provider))
        resolved_model = str(getattr(session.client, "model", model))
        route = str(getattr(session.client, "transport", route))
        cwd = session.ctx.cwd.resolve()
        reply = session.ask(
            PROMPT,
            review_skills=False,
            record_turn=False,
        ).strip()
    except Exception as error:  # noqa: BLE001 - release evidence boundary
        error_type = type(error).__name__
    finally:
        if session is not None:
            session.close()
    succeeded = error_type is None and reply == MARKER
    record: dict[str, object] = {
        "artifact_paths": {
            "browser_runtime": (
                str(browser_runtime) if browser_runtime is not None else "not-frozen"
            ),
            "probe": str(artifact_path.resolve()) if artifact_path else "stdout",
            "runtime_executable": str(Path(sys.executable).resolve()),
        },
        "cwd": str(cwd),
        "home": str(Path.home().resolve()),
        "marker": MARKER,
        "model": resolved_model,
        "provider": resolved_provider,
        "search_path": os.environ.get("PATH", ""),
        "reply_bytes": len(reply.encode()),
        "reply_sha256": hashlib.sha256(reply.encode()).hexdigest(),
        "route": route,
        "status": "pass" if succeeded else "fail",
    }
    if error_type is not None:
        record["error_type"] = error_type
    return record, 0 if succeeded else 1


def emit_probe(*, provider: str, model: str, output: Path | None) -> int:
    """Emit one canonical JSON record and optionally persist that same record."""
    record, status = run_probe(
        provider=provider,
        model=model,
        artifact_path=output,
    )
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"))
    print(encoded)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        _ = output.write_text(encoded + "\n", encoding="utf-8")
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument(
        "--provider", default="codex-cli", choices=("codex-cli",)
    )
    _ = parser.add_argument("--model", default="default")
    _ = parser.add_argument("--output", type=Path)
    args = vars(parser.parse_args(argv))
    provider = args.get("provider")
    model = args.get("model")
    output = args.get("output")
    if not isinstance(provider, str) or not isinstance(model, str):
        raise ValueError("provider and model must be strings")
    if output is not None and not isinstance(output, Path):
        raise ValueError("output must be a path")
    return emit_probe(provider=provider, model=model, output=output)


if __name__ == "__main__":
    raise SystemExit(main())
