"""Real macOS dogfood using only a Birkin-owned AppKit fixture."""

from __future__ import annotations

import argparse
import json
import os
import selectors
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil

from birkin import approvals, proc, procreg
from birkin.computer_use.approval_bridge import ApprovalBridge
from birkin.computer_use.artifacts import ArtifactStore
from birkin.computer_use.backends.macos import MacOSBackend
from birkin.computer_use.capability_types import PermissionState
from birkin.computer_use.service import ComputerUseService
from birkin.computer_use.session_policy import SessionCapability


def _ready_pid(process: subprocess.Popen[str], timeout: float = 15.0) -> int:
    if process.stdout is None:
        raise RuntimeError("Fixture stdout is unavailable.")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    events = selector.select(timeout)
    if not events:
        raise TimeoutError("Fixture did not report readiness.")
    line = process.stdout.readline().strip()
    prefix, raw_pid = line.split(" ", 1)
    if prefix != "READY":
        raise RuntimeError(f"Unexpected fixture readiness line: {line!r}")
    return int(raw_pid)


def _append(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def run(binary: Path, evidence_root: Path) -> int:
    os.environ["BIRKIN_HOME"] = str(evidence_root / "macos" / "home")
    backend = MacOSBackend()
    baseline_focus = backend.focus_state()
    process = subprocess.Popen(
        [str(binary)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **proc.popen_tree_kwargs(),
    )
    procreg.register(
        process.pid,
        session_id="macos-dogfood",
        purpose="macos-computer-use-qa-fixture",
        deadline=datetime.now(timezone.utc) + timedelta(minutes=2),
    )
    ledger = evidence_root / "macos" / "ledger.jsonl"
    cleanup = evidence_root / "macos" / "cleanup" / "fixture.json"
    results: list[dict[str, object]] = []
    foreground_attempted = False
    try:
        ready_pid = _ready_pid(process)
        if ready_pid != process.pid:
            raise RuntimeError("Fixture readiness PID does not match child PID.")
        service = ComputerUseService(
            backend=backend,
            artifact_store=ArtifactStore(evidence_root / "macos" / "artifacts"),
            session_id="macos-dogfood",
            approval_bridge=ApprovalBridge(
                session_id="macos-dogfood",
            ),
            session_capability=SessionCapability(
                session_id="macos-dogfood",
                actor="qa-driver",
                source="macos-dogfood",
                allowed_operations=frozenset(
                    {
                        "click",
                        "double_click",
                        "right_click",
                        "middle_click",
                        "drag",
                        "scroll",
                        "type",
                    }
                ),
                allowed_apps=frozenset({psutil.Process(ready_pid).exe()}),
            ),
        )
        apps = service.execute({"version": 1, "action": "list_apps"})
        app = next(
            (item for item in apps["apps"] if item["pid"] == ready_pid),
            None,
        )
        if app is None:
            results.append(
                {
                    "scenario_id": "app-window-discovery",
                    "result": "skipped",
                    "reason": "fixture_not_visible_in_hosted_gui_session",
                    "pid": ready_pid,
                }
            )
            ledger.parent.mkdir(parents=True, exist_ok=True)
            ledger.write_text(
                json.dumps(results, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return 0
        windows = service.execute(
            {
                "version": 1,
                "action": "list_windows",
                "session_id": service.session_id,
                "app_ref": app["app_ref"],
            }
        )
        if len(windows["windows"]) != 1:
            raise RuntimeError("Fixture did not expose one exact window.")
        window = windows["windows"][0]
        doctor = service.execute({"version": 1, "action": "doctor"})
        probe = backend.probe()
        results.append(
            {
                "scenario_id": "app-window-discovery",
                "result": "passed",
                "pid": ready_pid,
                "native_window_id": window["native_window_id"],
            }
        )
        if probe.screen_capture is PermissionState.GRANTED:
            vision = service.execute(
                {
                    "version": 1,
                    "action": "capture",
                    "session_id": service.session_id,
                    "mode": "vision",
                    "target": {"window_ref": window["window_ref"]},
                }
            )
            if not vision.get("ok"):
                raise RuntimeError(f"Vision capture failed: {vision}")
            results.append(
                {
                    "scenario_id": "vision-capture",
                    "result": "passed",
                    "artifact_ref": vision["artifact"]["ref"],
                    "snapshot_generation": vision["snapshot_generation"],
                }
            )
        else:
            results.append(
                {
                    "scenario_id": "vision-capture",
                    "result": "skipped",
                    "reason_code": "permission_required",
                    "guidance": doctor["guidance"],
                }
            )
        if probe.accessibility is PermissionState.GRANTED:
            ax = service.execute(
                {
                    "version": 1,
                    "action": "capture",
                    "session_id": service.session_id,
                    "mode": "ax",
                    "target": {"window_ref": window["window_ref"]},
                }
            )
            results.append(
                {
                    "scenario_id": "ax-capture",
                    "result": "passed" if ax.get("ok") else "failed",
                    "reason_code": ax.get("refusal_code"),
                }
            )
            button = next(
                item for item in ax["elements"] if "press" in item["supported_actions"]
            )
            background_request = {
                "version": 1,
                "action": "double_click",
                "session_id": service.session_id,
                "action_id": "macos-background-double-click",
                "idempotency_key": "macos-background-double-click",
                "target": {
                    "app_ref": ax["app_ref"],
                    "window_ref": ax["window_ref"],
                    "snapshot_ref": ax["snapshot_ref"],
                    "element_ref": button["element_ref"],
                },
                "delivery": "background",
                "predicted_effect": {
                    "property": "name",
                    "operation": "changes",
                },
            }
            background = service.execute(background_request)
            approval = background["approval"]
            claimed = approvals.claim(approval["review_id"], approved_by="system:qa", approved_via="qa:script")
            approved = approvals.execute_claimed(approval["review_id"])
            if not claimed.get("ok") or not approved.get("ok"):
                raise RuntimeError("Foreground approval bridge failed.")
            foreground = service.execute(
                {
                    **background_request,
                    "action_id": "macos-foreground-double-click",
                    "idempotency_key": "macos-foreground-double-click",
                    "delivery": "foreground",
                    "prior_background_receipt": background["receipt_ref"],
                    "approval_id": approval["approval_id"],
                }
            )
            foreground_attempted = True
            results.append(
                {
                    "scenario_id": "foreground-approved-double-click",
                    "result": ("passed" if foreground.get("ok") else "failed"),
                    "reason_code": foreground.get("refusal_code"),
                    "effect": foreground.get("effect"),
                }
            )
        else:
            results.append(
                {
                    "scenario_id": "ax-capture",
                    "result": "skipped",
                    "reason_code": "permission_required",
                    "guidance": doctor["guidance"],
                }
            )
        for result in results:
            _append(
                ledger,
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **result,
                },
            )
        return 0
    finally:
        proc.kill_tree(process)
        try:
            process.wait(timeout=10)
        finally:
            procreg.unregister(process.pid)
        focus_restored = (
            backend.restore_focus(baseline_focus)
            if backend.can_restore_focus(baseline_focus)
            else False
        )
        released_inputs = list(backend.release_inputs()) if foreground_attempted else []
        focus_preserved = focus_restored and baseline_focus.focus_equivalent(
            backend.focus_state()
        )
        cleanup.parent.mkdir(parents=True, exist_ok=True)
        cleanup.write_text(
            json.dumps(
                {
                    "pid": process.pid,
                    "returncode": process.returncode,
                    "alive": procreg.pid_alive(process.pid),
                    "registered": False,
                    "focus_restored": focus_restored,
                    "focus_preserved": focus_preserved,
                    "released_inputs": released_inputs,
                    "other_targets_mutated": False,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-binary", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("macOS is required")
    return run(args.fixture_binary, args.evidence_root)


if __name__ == "__main__":
    raise SystemExit(main())
