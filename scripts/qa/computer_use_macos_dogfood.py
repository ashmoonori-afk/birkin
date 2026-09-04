"""Truthful macOS Computer Use evidence against a Birkin-owned AppKit fixture."""

from __future__ import annotations

import argparse
import json
import os
import selectors
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Protocol, cast

from birkin import proc, procreg
from birkin.computer_use.approval_bridge import ApprovalBridge
from birkin.computer_use.artifacts import ArtifactStore
from birkin.computer_use.backends.macos import MacOSBackend
from birkin.computer_use.capability_types import PermissionState
from birkin.computer_use.models import FocusSnapshot
from birkin.computer_use.service import ComputerUseService
from birkin.computer_use.session_policy import SessionCapability

Mode = Literal["hosted", "permissioned-required"]
REQUIRED_SCENARIOS = frozenset(
    {
        "fixture-readiness",
        "app-window-discovery",
        "desktop-permissions",
        "vision-capture",
        "ax-capture",
        "confirmed-mutation",
        "cleanup",
    }
)
HOSTED_SCENARIOS = frozenset({"fixture-readiness", "hosted-limitations", "cleanup"})


class FixtureProcess(Protocol):
    pid: int
    returncode: int | None

    def wait(self, timeout: float | None = None) -> int: ...


class CleanupBackend(Protocol):
    def release_inputs(self) -> tuple[str, ...]: ...
    def focus_state(self) -> FocusSnapshot: ...
    def can_restore_focus(self, snapshot: FocusSnapshot) -> bool: ...
    def restore_focus(self, snapshot: FocusSnapshot) -> bool: ...


class CleanupRuntime(Protocol):
    def kill(self, process: FixtureProcess) -> None: ...
    def unregister(self, pid: int) -> None: ...
    def pid_alive(self, pid: int) -> bool: ...


class SystemCleanupRuntime:
    def kill(self, process: FixtureProcess) -> None:
        proc.kill_tree(cast(subprocess.Popen[str], cast(object, process)))

    def unregister(self, pid: int) -> None:
        procreg.unregister(pid)

    def pid_alive(self, pid: int) -> bool:
        return procreg.pid_alive(pid)


SYSTEM_CLEANUP_RUNTIME = SystemCleanupRuntime()


def ready_pid(process: subprocess.Popen[str], timeout: float = 20.0) -> int:
    """Await the fixture's exact, one-shot ready event; never poll UI state."""
    if process.stdout is None:
        raise RuntimeError("Fixture stdout is unavailable.")
    selector = selectors.DefaultSelector()
    try:
        _ = selector.register(process.stdout, selectors.EVENT_READ)
        if not selector.select(timeout):
            raise TimeoutError("Fixture did not report readiness.")
        line = cast(str, process.stdout.readline())
        raw = cast(object, json.loads(line))
    finally:
        selector.close()
    expected = {
        "event": "fixture.ready",
        "pid": process.pid,
        "window_title": "Birkin Computer Use QA Fixture",
        "counter": "count=0",
        "application_active": True,
        "window_key": True,
        "window_visible": True,
    }
    if raw != expected:
        raise RuntimeError(f"Unexpected fixture readiness event: {raw!r}")
    return process.pid


def make_record(
    *,
    mode: Mode,
    scenario_id: str,
    result: Literal["passed", "failed", "skipped", "limited"],
    mandatory: bool,
    reason_code: str | None = None,
    evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": "macos",
        "mode": mode,
        "scenario_id": scenario_id,
        "mandatory": mandatory,
        "result": result,
        "reason_code": reason_code,
        "evidence": evidence or {},
    }


def append_record(path: Path, record: dict[str, object]) -> None:
    """Append exactly one normalized JSON object as one JSONL line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        _ = handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def accepted(mode: Mode, records: list[dict[str, object]]) -> bool:
    required = HOSTED_SCENARIOS if mode == "hosted" else REQUIRED_SCENARIOS
    by_scenario = {str(item["scenario_id"]): item for item in records}
    return all(
        scenario in by_scenario
        and by_scenario[scenario]["mandatory"] is True
        and by_scenario[scenario]["result"] == "passed"
        for scenario in required
    )


def cleanup_fixture(
    process: FixtureProcess | None,
    backend: CleanupBackend | None,
    baseline_focus: FocusSnapshot | None,
    *,
    registration_attempted: bool,
    runtime: CleanupRuntime = SYSTEM_CLEANUP_RUNTIME,
) -> dict[str, object]:
    errors: list[str] = []
    released_inputs: list[str] = []
    focus_restored = False
    focus_preserved = False
    pid = process.pid if process is not None else None

    if backend is not None:
        try:
            released_inputs = list(backend.release_inputs())
        except Exception as exc:  # cleanup failures are evidence, not hidden
            errors.append(f"release_inputs:{type(exc).__name__}:{exc}")
    if process is not None:
        try:
            runtime.kill(process)
            _ = process.wait(timeout=10)
        except Exception as exc:  # cleanup failures are evidence, not hidden
            errors.append(f"kill_fixture:{type(exc).__name__}:{exc}")
        finally:
            if registration_attempted:
                try:
                    runtime.unregister(process.pid)
                except Exception as exc:  # cleanup failures are evidence, not hidden
                    errors.append(f"unregister:{type(exc).__name__}:{exc}")
    if backend is not None and baseline_focus is not None:
        try:
            current_focus = backend.focus_state()
            if baseline_focus.focus_equivalent(current_focus):
                focus_restored = True
                focus_preserved = True
            else:
                focus_restored = backend.can_restore_focus(
                    baseline_focus
                ) and backend.restore_focus(baseline_focus)
                focus_preserved = focus_restored and baseline_focus.focus_equivalent(
                    backend.focus_state()
                )
        except Exception as exc:  # cleanup failures are evidence, not hidden
            errors.append(f"restore_focus:{type(exc).__name__}:{exc}")

    alive = bool(pid is not None and runtime.pid_alive(pid))
    return {
        "pid": pid,
        "returncode": process.returncode if process is not None else None,
        "alive": alive,
        "registered": False,
        "focus_restored": focus_restored,
        "focus_preserved": focus_preserved,
        "released_inputs": released_inputs,
        "other_targets_mutated": False,
        "errors": errors,
        "ok": bool(
            process is not None
            and not alive
            and focus_preserved
            and not errors
        ),
    }


def _object_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return cast(dict[str, object], value)


def _object_dicts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [
        cast(dict[str, object], item)
        for item in items
        if isinstance(item, dict)
    ]


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _execute(
    service: ComputerUseService,
    request: dict[str, object],
) -> dict[str, object]:
    return cast(dict[str, object], service.execute(request))


def create_service(
    backend: MacOSBackend,
    evidence_root: Path,
    app_identity: str,
) -> ComputerUseService:
    return ComputerUseService(
        backend=backend,
        artifact_store=ArtifactStore(evidence_root / "macos" / "artifacts"),
        session_id="macos-dogfood",
        approval_bridge=ApprovalBridge(session_id="macos-dogfood"),
        session_capability=SessionCapability(
            session_id="macos-dogfood",
            actor="qa-driver",
            source="macos-dogfood",
            allowed_operations=frozenset({"type"}),
            allowed_apps=frozenset({app_identity}),
        ),
    )


def mutation_confirmed(mutation: dict[str, object]) -> bool:
    return bool(
        mutation.get("ok")
        and mutation.get("effect") == "confirmed"
        and mutation.get("receipt_ref")
        and _object_dict(mutation.get("focus")).get("preserved") is True
    )


def permissioned_evidence(
    backend: MacOSBackend,
    evidence_root: Path,
    pid: int,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    probe = backend.probe()
    permissions_ok = bool(
        probe.interactive
        and probe.accessibility is PermissionState.GRANTED
        and probe.screen_capture is PermissionState.GRANTED
    )
    records.append(
        make_record(
            mode="permissioned-required",
            scenario_id="desktop-permissions",
            result="passed" if permissions_ok else "failed",
            mandatory=True,
            reason_code=None if permissions_ok else "permission_required",
            evidence={
                "interactive": probe.interactive,
                "accessibility": probe.accessibility.value,
                "screen_capture": probe.screen_capture.value,
                "responsible_process": probe.responsible_process,
            },
        )
    )
    if not permissions_ok:
        return records

    observed_app = next(
        (item for item in backend.list_apps() if item.pid == pid),
        None,
    )
    observed_windows = (
        [
            item
            for item in backend.list_windows(observed_app)
            if item.title == "Birkin Computer Use QA Fixture"
        ]
        if observed_app is not None
        else []
    )
    discovery_ok = observed_app is not None and len(observed_windows) == 1
    service = (
        create_service(backend, evidence_root, observed_app.native_identity)
        if discovery_ok and observed_app is not None
        else None
    )
    app: dict[str, object] | None = None
    window: dict[str, object] | None = None
    if service is not None:
        apps = _execute(service, {"version": 1, "action": "list_apps"})
        app = next(
            (item for item in _object_dicts(apps.get("apps")) if item.get("pid") == pid),
            None,
        )
        if app is not None:
            windows = _execute(
                service,
                {
                    "version": 1,
                    "action": "list_windows",
                    "session_id": service.session_id,
                    "app_ref": app["app_ref"],
                },
            )
            matches = [
                item
                for item in _object_dicts(windows.get("windows"))
                if item.get("title") == "Birkin Computer Use QA Fixture"
            ]
            window = matches[0] if len(matches) == 1 else None
    records.append(
        make_record(
            mode="permissioned-required",
            scenario_id="app-window-discovery",
            result="passed" if window is not None else "failed",
            mandatory=True,
            reason_code=None if window is not None else "fixture_not_discovered",
            evidence={"pid": pid, "native_window_id": window["native_window_id"] if window else None},
        )
    )
    if window is None or service is None:
        return records

    vision = _execute(
        service,
        {
            "version": 1,
            "action": "capture",
            "session_id": service.session_id,
            "mode": "vision",
            "target": {"window_ref": window["window_ref"]},
        }
    )
    records.append(
        make_record(
            mode="permissioned-required",
            scenario_id="vision-capture",
            result="passed" if vision.get("ok") else "failed",
            mandatory=True,
            reason_code=_optional_string(vision.get("refusal_code")),
            evidence={"artifact_ref": _object_dict(vision.get("artifact")).get("ref")},
        )
    )
    ax = _execute(
        service,
        {
            "version": 1,
            "action": "capture",
            "session_id": service.session_id,
            "mode": "ax",
            "target": {"window_ref": window["window_ref"]},
        }
    )
    ax_ok = bool(ax.get("ok"))
    records.append(
        make_record(
            mode="permissioned-required",
            scenario_id="ax-capture",
            result="passed" if ax_ok else "failed",
            mandatory=True,
            reason_code=_optional_string(ax.get("refusal_code")),
            evidence={"element_count": len(_object_dicts(ax.get("elements")))},
        )
    )
    if not vision.get("ok") or not ax_ok:
        return records

    editable = next(
        (
            item
            for item in _object_dicts(ax.get("elements"))
            if "set_value" in cast(list[object], item.get("supported_actions", []))
        ),
        None,
    )
    if editable is None:
        mutation: dict[str, object] = {
            "ok": False,
            "effect": "unverifiable",
            "refusal_code": "fixture_editable_not_discovered",
        }
    else:
        mutation = _execute(
            service,
            {
                "version": 1,
                "action": "type",
                "session_id": service.session_id,
                "action_id": "macos-owned-fixture-type",
                "idempotency_key": "macos-owned-fixture-type-v1",
                "target": {
                    "app_ref": ax["app_ref"],
                    "window_ref": ax["window_ref"],
                    "snapshot_ref": ax["snapshot_ref"],
                    "element_ref": editable["element_ref"],
                },
                "text": "after",
                "mode": "replace",
                "delivery": "background",
                "predicted_effect": {
                    "property": "value",
                    "operation": "equals",
                    "value": "after",
                },
            }
        )
    mutation_ok = mutation_confirmed(mutation)
    records.append(
        make_record(
            mode="permissioned-required",
            scenario_id="confirmed-mutation",
            result="passed" if mutation_ok else "failed",
            mandatory=True,
            reason_code=(
                _optional_string(mutation.get("refusal_code"))
                if not mutation_ok
                else None
            ),
            evidence={
                "effect": mutation.get("effect"),
                "receipt_ref": mutation.get("receipt_ref"),
                "focus_preserved": _object_dict(mutation.get("focus")).get("preserved"),
                "owned_fixture_only": True,
            },
        )
    )
    return records


def run(binary: Path, evidence_root: Path, mode: Mode) -> int:
    platform_root = evidence_root / "macos"
    os.environ["BIRKIN_HOME"] = str(platform_root / "home")
    ledger = platform_root / "ledger.jsonl"
    cleanup_path = platform_root / "cleanup" / "fixture.json"
    ledger.unlink(missing_ok=True)
    records: list[dict[str, object]] = []
    backend: MacOSBackend | None = None
    baseline_focus: FocusSnapshot | None = None
    process: subprocess.Popen[str] | None = None
    registration_attempted = False

    try:
        backend = MacOSBackend()
        baseline_focus = backend.focus_state()
        process = subprocess.Popen(
            [str(binary)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **proc.popen_tree_kwargs(),
        )
        registration_attempted = True
        procreg.register(
            process.pid,
            session_id="macos-dogfood",
            purpose="macos-computer-use-qa-fixture",
            deadline=datetime.now(timezone.utc) + timedelta(minutes=2),
        )
        pid = ready_pid(process)
        records.append(
            make_record(
                mode=mode,
                scenario_id="fixture-readiness",
                result="passed",
                mandatory=True,
                evidence={"pid": pid, "event": "fixture.ready"},
            )
        )
        if mode == "hosted":
            records.append(
                make_record(
                    mode=mode,
                    scenario_id="hosted-limitations",
                    result="passed",
                    mandatory=True,
                    reason_code="hosted_runner_tcc_not_provisioned",
                    evidence={
                        "deterministic": True,
                        "desktop_effects_attempted": False,
                        "accepts_permission_skip_as_effect_evidence": False,
                        "requires_permissioned_followup": True,
                    },
                )
            )
            for scenario in sorted(REQUIRED_SCENARIOS - HOSTED_SCENARIOS):
                records.append(
                    make_record(
                        mode=mode,
                        scenario_id=scenario,
                        result="limited",
                        mandatory=False,
                        reason_code="hosted_runner_tcc_not_provisioned",
                    )
                )
        else:
            records.extend(permissioned_evidence(backend, evidence_root, pid))
    except Exception as exc:
        records.append(
            make_record(
                mode=mode,
                scenario_id="driver-error",
                result="failed",
                mandatory=True,
                reason_code=type(exc).__name__,
                evidence={"message": str(exc)},
            )
        )
    finally:
        cleanup = cleanup_fixture(
            process,
            backend,
            baseline_focus,
            registration_attempted=registration_attempted,
        )
        cleanup_path.parent.mkdir(parents=True, exist_ok=True)
        _ = cleanup_path.write_text(
            json.dumps(cleanup, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        records.append(
            make_record(
                mode=mode,
                scenario_id="cleanup",
                result="passed" if cleanup["ok"] else "failed",
                mandatory=True,
                reason_code=None if cleanup["ok"] else "cleanup_incomplete",
                evidence=cleanup,
            )
        )
        for item in records:
            append_record(ledger, item)

    return 0 if accepted(mode, records) else 1


class Arguments(argparse.Namespace):
    def __init__(self) -> None:
        super().__init__()
        self.fixture_binary: Path = Path()
        self.evidence_root: Path = Path()
        self.mode: Mode = "hosted"


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--fixture-binary", type=Path, required=True)
    _ = parser.add_argument("--evidence-root", type=Path, required=True)
    _ = parser.add_argument(
        "--mode",
        choices=("hosted", "permissioned-required"),
        required=True,
    )
    args = parser.parse_args(namespace=Arguments())
    if sys.platform != "darwin":
        parser.error("macOS is required")
    return run(args.fixture_binary, args.evidence_root, args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
