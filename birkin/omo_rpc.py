"""JSONL RPC client for the locally installed OMO controller."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Sequence, TypeAlias

from .proc import kill_tree, popen_tree_kwargs


JsonValue: TypeAlias = (
    str | int | float | bool | None
    | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]


class RpcError(RuntimeError):
    """The local OMO RPC process could not complete a request."""


@dataclass(frozen=True, slots=True)
class OmoState:
    """The OMO session state consumed by the gateway."""

    session_id: str | None
    is_streaming: bool


def default_omo_command() -> tuple[str, ...]:
    """Start OMO only through its documented local RPC mode."""
    executable = shutil.which("omo.cmd") or shutil.which("omo")
    if executable is None:
        raise RpcError("The omo executable is not on PATH.")
    path = Path(executable)
    if os.name == "nt" and path.suffix.lower() in {".cmd", ".bat"}:
        node = shutil.which("node.exe") or shutil.which("node")
        launcher = path.parent / "node_modules" / "omo-ai" / "bin" / "omo.js"
        if node is None or not launcher.is_file():
            raise RpcError("Could not resolve the Node.js OMO launcher.")
        return node, str(launcher), "--mode", "rpc", "--no-session", "--approve"
    return str(path), "--mode", "rpc", "--no-session", "--approve"


def command_for_session(command: Sequence[str], session_path: Path) -> tuple[str, ...]:
    """Replace any existing OMO session option with the selected session."""
    result: list[str] = []
    skip_next = False
    for argument in command:
        if skip_next:
            skip_next = False
        elif argument == "--session":
            skip_next = True
        elif argument != "--no-session":
            result.append(argument)
    session = str(session_path)
    windows_path = PureWindowsPath(session)
    if windows_path.drive:
        session = str(windows_path)
    return *result, "--session", session


class OmoRpcClient:
    """One long-lived JSONL RPC connection to a local OMO process."""

    def __init__(self, command: Sequence[str] | None = None, timeout: float = 900) -> None:
        self._command = tuple(command) if command else None
        self._timeout = timeout
        self._process: subprocess.Popen[str] | None = None
        self._condition = threading.Condition()
        self._write_lock = threading.Lock()
        self._responses: dict[str, JsonObject] = {}
        self._settled_count = 0
        self._reader_error: str | None = None
        self._stderr: deque[str] = deque(maxlen=20)
        self._reader_threads: tuple[threading.Thread, threading.Thread] | None = None

    def _start(self) -> subprocess.Popen[str]:
        if self._process is not None:
            return self._process
        process = subprocess.Popen(
            self._command or default_omo_command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **popen_tree_kwargs(),
        )
        self._process = process
        readers = (threading.Thread(target=self._read_stdout, daemon=True), threading.Thread(target=self._read_stderr, daemon=True))
        self._reader_threads = readers
        for reader in readers:
            reader.start()
        return process

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            with self._condition:
                self._reader_error = "OMO RPC stdout is unavailable."
                self._condition.notify_all()
            return
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                response: JsonObject = {
                    str(key): value for key, value in message.items()
                }
                with self._condition:
                    request_id = response.get("id")
                    if response.get("type") == "response" and request_id:
                        self._responses[str(request_id)] = response
                    elif response.get("type") == "agent_settled":
                        self._settled_count += 1
                    self._condition.notify_all()
        finally:
            with self._condition:
                self._reader_error = "\n".join(self._stderr) or "OMO RPC process exited."
                self._condition.notify_all()

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            self._stderr.append("OMO RPC stderr is unavailable.")
            return
        for line in process.stderr:
            self._stderr.append(line.rstrip())

    def _request(self, kind: str, **payload: str) -> JsonObject:
        process = self._start()
        request_id = uuid.uuid4().hex
        with self._write_lock:
            if process.stdin is None:
                raise RpcError("OMO RPC stdin is unavailable.")
            process.stdin.write(json.dumps({"id": request_id, "type": kind, **payload}) + "\n")
            process.stdin.flush()
        deadline = time.monotonic() + self._timeout
        with self._condition:
            while request_id not in self._responses:
                if self._reader_error is not None:
                    raise RpcError(self._reader_error)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RpcError(f"Timed out waiting for OMO {kind}.")
                self._condition.wait(remaining)
            response = self._responses.pop(request_id)
        if response.get("success") is not True:
            raise RpcError(str(response.get("error") or f"OMO {kind} failed."))
        data = response.get("data")
        return data if isinstance(data, dict) else {}

    def switch_session(self, path: Path) -> None:
        self.close()
        self._command = command_for_session(self._command or default_omo_command(), path)
        self.get_state()

    def prompt(self, message: str) -> str:
        with self._condition:
            settled_before = self._settled_count
        self._request("prompt", message=message)
        deadline = time.monotonic() + self._timeout
        with self._condition:
            while self._settled_count <= settled_before:
                if self._reader_error is not None:
                    raise RpcError(self._reader_error)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RpcError("Timed out waiting for the OMO turn to settle.")
                self._condition.wait(remaining)
        return self.get_last_assistant_text() or "(OMO completed without a text reply.)"

    def steer(self, message: str) -> None:
        self._request("steer", message=message)

    def abort(self) -> None:
        self._request("abort")

    def get_state(self) -> OmoState:
        state = self._request("get_state")
        session_id = state.get("sessionId")
        return OmoState(
            session_id=str(session_id) if session_id is not None else None,
            is_streaming=state.get("isStreaming") is True,
        )

    def get_last_assistant_text(self) -> str | None:
        text = self._request("get_last_assistant_text").get("text")
        return str(text) if text is not None else None

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None and process.stdin is not None:
            try:
                process.stdin.close()
            except OSError as exc:
                self._stderr.append(f"stdin close failed: {exc}")
        if process.poll() is None:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                kill_tree(process)
                process.wait(timeout=3)
        if self._reader_threads is not None:
            for thread in self._reader_threads:
                thread.join(timeout=1)
        with self._condition:
            self._process = None
            self._reader_threads = None
            self._responses.clear()
            self._settled_count = 0
            self._reader_error = None
