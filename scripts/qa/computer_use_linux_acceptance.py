"""Real Linux X11/AT-SPI acceptance using a Birkin-owned GTK fixture."""

from __future__ import annotations

import argparse
import json
import os
import selectors
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from birkin import approvals, proc, procreg
from birkin.computer_use.approval_bridge import ApprovalBridge
from birkin.computer_use.artifacts import ArtifactStore
from birkin.computer_use.backends.linux import LinuxBackend
from birkin.computer_use.service import ComputerUseService


def _ready_pid(process: subprocess.Popen[str]) -> int:
    if process.stdout is None:
        raise RuntimeError("Fixture stdout is unavailable.")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    if not selector.select(20):
        raise TimeoutError("GTK fixture did not report readiness.")
    prefix, raw_pid = process.stdout.readline().strip().split(" ", 1)
    if prefix != "READY":
        raise RuntimeError("Unexpected fixture readiness event.")
    return int(raw_pid)


def run(fixture: Path, evidence_root: Path) -> int:
    os.environ["BIRKIN_HOME"] = str(evidence_root / "linux" / "home")
    process = subprocess.Popen(
        [str(fixture)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **proc.popen_tree_kwargs(),
    )
    procreg.register(
        process.pid,
        session_id="linux-acceptance",
        purpose="linux-computer-use-qa-fixture",
        deadline=datetime.now(timezone.utc) + timedelta(minutes=3),
    )
    ledger = evidence_root / "linux" / "ledger.json"
    try:
        pid = _ready_pid(process)
        backend = LinuxBackend()
        service = ComputerUseService(
            backend=backend,
            artifact_store=ArtifactStore(evidence_root / "linux" / "artifacts"),
            session_id="linux-acceptance",
            approval_bridge=ApprovalBridge(
                session_id="linux-acceptance",
            ),
        )
        apps = service.execute({"version": 1, "action": "list_apps"})
        app = next(item for item in apps["apps"] if item["pid"] == pid)
        windows = service.execute(
            {
                "version": 1,
                "action": "list_windows",
                "session_id": service.session_id,
                "app_ref": app["app_ref"],
            }
        )
        window = next(
            item
            for item in windows["windows"]
            if item["title"] == "Birkin Computer Use QA Fixture"
        )
        vision = service.execute(
            {
                "version": 1,
                "action": "capture",
                "session_id": service.session_id,
                "mode": "vision",
                "target": {"window_ref": window["window_ref"]},
            }
        )
        ax = service.execute(
            {
                "version": 1,
                "action": "capture",
                "session_id": service.session_id,
                "mode": "ax",
                "target": {"window_ref": window["window_ref"]},
            }
        )
        editable = next(
            item for item in ax["elements"] if "set_value" in item["supported_actions"]
        )
        typed = service.execute(
            {
                "version": 1,
                "action": "type",
                "session_id": service.session_id,
                "action_id": "linux-type",
                "idempotency_key": "linux-type-1",
                "target": {
                    "app_ref": ax["app_ref"],
                    "window_ref": ax["window_ref"],
                    "snapshot_ref": ax["snapshot_ref"],
                    "element_ref": editable["element_ref"],
                },
                "text": "typed",
                "mode": "replace",
                "delivery": "background",
                "predicted_effect": {
                    "property": "value",
                    "operation": "equals",
                    "value": "typed",
                },
            }
        )
        fresh = service.execute(
            {
                "version": 1,
                "action": "capture",
                "session_id": service.session_id,
                "mode": "ax",
                "target": {"window_ref": window["window_ref"]},
            }
        )
        button = next(
            item for item in fresh["elements"] if "press" in item["supported_actions"]
        )
        target = {
            "app_ref": fresh["app_ref"],
            "window_ref": fresh["window_ref"],
            "snapshot_ref": fresh["snapshot_ref"],
            "element_ref": button["element_ref"],
        }
        background_request = {
            "version": 1,
            "action": "double_click",
            "session_id": service.session_id,
            "action_id": "linux-background-double-click",
            "idempotency_key": "linux-background-double-click",
            "target": target,
            "delivery": "background",
            "predicted_effect": {
                "property": "name",
                "operation": "changes",
            },
        }
        background = service.execute(background_request)
        approval = background["approval"]
        claimed = approvals.claim(approval["review_id"])
        approved = approvals.execute_claimed(approval["review_id"])
        if not claimed.get("ok") or not approved.get("ok"):
            raise RuntimeError("Foreground approval bridge failed.")
        foreground = service.execute(
            {
                **background_request,
                "action_id": "linux-foreground-double-click",
                "idempotency_key": "linux-foreground-double-click",
                "delivery": "foreground",
                "prior_background_receipt": background["receipt_ref"],
                "approval_id": approval["approval_id"],
            }
        )
        result = {
            "platform": "linux",
            "pid": pid,
            "native_window_id": window["native_window_id"],
            "vision": vision,
            "ax_element_count": len(ax["elements"]),
            "mutation": typed,
            "foreground_fallback": foreground,
        }
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return 0 if vision.get("ok") and typed.get("ok") and foreground.get("ok") else 1
    finally:
        proc.kill_tree(process)
        try:
            process.wait(timeout=10)
        finally:
            procreg.unregister(process.pid)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("Linux is required")
    return run(args.fixture, args.evidence_root)


if __name__ == "__main__":
    raise SystemExit(main())
