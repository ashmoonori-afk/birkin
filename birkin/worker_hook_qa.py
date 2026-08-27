"""Deterministic QA driver for approval-gated worker continuation."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Sequence
from unittest.mock import patch

from . import approvals, store


def run(decision: str) -> int:
    """Exercise approval and continuation without executing a real action."""
    if decision not in {"approve", "reject"}:
        raise ValueError("decision must be approve or reject")
    counts = {"action_runs": 0, "resume_runs": 0}

    def execute_action(*unused_args: Any, **unused_kwargs: Any) -> str:
        counts["action_runs"] += 1
        return "qa action complete"

    def on_event(event: dict[str, Any]) -> None:
        if event.get("type") != "worker_resume":
            raise ValueError("unexpected worker hook event")
        counts["resume_runs"] += 1

    previous_home = os.environ.get("BIRKIN_HOME")
    summary: dict[str, Any]
    with tempfile.TemporaryDirectory(prefix="birkin-worker-hook-qa-") as home:
        os.environ["BIRKIN_HOME"] = home
        try:
            with patch.object(approvals, "execute_action", execute_action):
                queued = approvals.propose(
                    category="shell",
                    title="worker hook QA",
                    description="prove approval gates action and continuation",
                    payload={"command": "not executed by QA"},
                    cfg={"auto_approve": []},
                    origin="odyssey",
                    continuation={
                        "schema": 1,
                        "handler": "worker.resume.v1",
                        "worker": "odyssey",
                        "context": {"checkpoint": "qa"},
                    },
                )
                before = store.get_pending(queued["id"])
                if decision == "approve":
                    result = approvals.approve(queued["id"], on_event=on_event, approved_by="system:qa", approved_via="qa:script")
                else:
                    result = approvals.reject(queued["id"], reason="qa rejection", rejected_by="system:qa", rejected_via="qa:script")
                final = store.get_pending(queued["id"])
        finally:
            if previous_home is None:
                os.environ.pop("BIRKIN_HOME", None)
            else:
                os.environ["BIRKIN_HOME"] = previous_home
        summary = {
            "status": final.get("status") if final else "missing",
            "action_runs": counts["action_runs"],
            "resume_runs": counts["resume_runs"],
            "pending_before": bool(
                before and before.get("status") == "pending"
            ),
            "ok": bool(result.get("ok")),
        }
    summary["cleaned"] = not Path(home).exists()
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["ok"] and summary["cleaned"] else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Run the QA driver as ``python -m birkin.worker_hook_qa``."""
    parser = argparse.ArgumentParser(
        prog="python -m birkin.worker_hook_qa",
        description=__doc__,
    )
    parser.add_argument(
        "--decision",
        required=True,
        choices=("approve", "reject"),
    )
    args = parser.parse_args(argv)
    return run(args.decision)


if __name__ == "__main__":
    raise SystemExit(main())
