"""Real OMO process harness for live-bridge QA."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import TextIO, cast

from birkin.omo_bridge import bridge_extension_path

QA_PREFIX = "BIRKIN_OMO_BRIDGE_QA "


@dataclass(frozen=True, slots=True)
class OmoHarnessConfig:
    omo: Path
    root: Path
    registry: Path


@dataclass(slots=True)
class OmoHarness:
    session_id: str
    process: subprocess.Popen[str]
    events: queue.Queue[dict[str, object]]
    reader: threading.Thread | None = None

    def wait_event(self, expected: str, timeout: float) -> dict[str, object]:
        deadline = monotonic() + timeout
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Timed out waiting for {expected!r} from {self.session_id}."
                )
            try:
                event = self.events.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(
                    f"Timed out waiting for {expected!r} from {self.session_id}."
                ) from exc
            if event.get("event") == expected:
                return event

    def delivery_events(self) -> tuple[dict[str, object], ...]:
        found: list[dict[str, object]] = []
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                return tuple(found)
            if event.get("event") == "delivery":
                found.append(event)

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                _ = self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                _ = self.process.wait(timeout=5)
        if self.reader is not None:
            self.reader.join(timeout=2)


def start_omo(
    config: OmoHarnessConfig,
    session_id: str,
) -> OmoHarness:
    agent_dir = config.root / "agents" / session_id
    session_dir = config.root / "sessions" / session_id
    workspace = config.root / "workspaces" / session_id
    for path in (agent_dir, session_dir, workspace):
        path.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.update(
        {
            "BIRKIN_OMO_BRIDGE_QA": "1",
            "BIRKIN_OMO_LIVE_DIR": str(config.registry),
            "OMO_CODING_AGENT_DIR": str(agent_dir),
        }
    )
    command = [
        *(
            ["node", str(config.omo)]
            if config.omo.suffix == ".js"
            else [str(config.omo)]
        ),
        "--mode",
        "rpc",
        "--session-id",
        session_id,
        "--session-dir",
        str(session_dir),
        "--no-extensions",
        "--extension",
        str(bridge_extension_path()),
        "--approve",
    ]
    process = subprocess.Popen(
        command,
        cwd=workspace,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    harness = OmoHarness(session_id, process, queue.Queue())
    harness.reader = threading.Thread(
        target=_read_events,
        args=(harness,),
        name=f"omo-bridge-events-{session_id}",
        daemon=True,
    )
    harness.reader.start()
    return harness


def _decode_event(line: str) -> dict[str, object] | None:
    if not line.startswith(QA_PREFIX):
        return None
    decoded = cast(object, json.loads(line[len(QA_PREFIX) :]))
    if not isinstance(decoded, dict):
        raise TypeError("OMO bridge QA event must be an object.")
    return cast(dict[str, object], decoded)


def _read_events(harness: OmoHarness) -> None:
    stderr = harness.process.stderr
    if stderr is None:
        return
    stream = cast(TextIO, stderr)
    for line in stream:
        event = _decode_event(line.rstrip())
        if event is not None:
            harness.events.put(event)
