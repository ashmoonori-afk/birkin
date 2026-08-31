from __future__ import annotations

import json
import threading
from pathlib import Path

from birkin.omo_rpc import OmoState


class FakeRpc:
    def __init__(self) -> None:
        self.selected: Path | None = None
        self.prompts: list[str] = []
        self.prompt_called = threading.Event()
        self.steers: list[str] = []
        self.aborted = False
        self.closed = False

    def switch_session(self, path: Path) -> None:
        self.selected = path

    def prompt(self, message: str) -> str:
        self.prompts.append(message)
        self.prompt_called.set()
        return f"reply: {message}"

    def steer(self, message: str) -> None:
        self.steers.append(message)

    def abort(self) -> None:
        self.aborted = True

    def get_state(self) -> OmoState:
        return OmoState(session_id="abc123", is_streaming=False)

    def get_last_assistant_text(self) -> str | None:
        return "last reply"

    def close(self) -> None:
        self.closed = True


class BlockingRpc(FakeRpc):
    def __init__(self) -> None:
        super().__init__()
        self.prompt_started = threading.Event()
        self.release_prompt = threading.Event()
        self.prompt_finished = threading.Event()

    def prompt(self, message: str) -> str:
        self.prompts.append(message)
        self.prompt_called.set()
        self.prompt_started.set()
        if not self.release_prompt.wait(timeout=5):
            raise AssertionError("test did not release the blocked OMO prompt")
        self.prompt_finished.set()
        return f"reply: {message}"


class FailingRpc(FakeRpc):
    def __init__(self) -> None:
        super().__init__()
        self.prompt_failed = threading.Event()

    def prompt(self, message: str) -> str:
        self.prompts.append(message)
        self.prompt_called.set()
        try:
            raise OSError("background prompt failed")
        finally:
            self.prompt_failed.set()


def write_session(root: Path, session_id: str, cwd: str) -> Path:
    path = root / f"{session_id}.jsonl"
    path.write_text(
        json.dumps({"type": "session", "id": session_id, "cwd": cwd}) + "\n",
        encoding="utf-8",
    )
    return path
