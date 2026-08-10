"""Change-only cron monitor acquisition and persistent hash state."""

from __future__ import annotations

import hashlib
import subprocess
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import config, store
from .proc import shell_argv
from .tools.web import _GuardedRedirectHandler, _is_blocked_url

MAX_BYTES = 256 * 1024
DEFAULT_MAX_BYTES = MAX_BYTES


@dataclass(frozen=True)
class MonitorResult:
    changed: bool
    error: str | None
    diff_context: str
    content_tail: str


def clamp_max_bytes(value: Any) -> int:
    """Normalize a per-job byte limit without exceeding the hard cap."""
    try:
        size = int(value)
    except (TypeError, ValueError, OverflowError):
        size = DEFAULT_MAX_BYTES
    return max(1, min(MAX_BYTES, size))


def _state_dir() -> Path:
    path = config.birkin_home() / "monitor_state"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path(job_id: str) -> Path:
    job_id = str(job_id)
    if not job_id or Path(job_id).name != job_id or job_id in (".", ".."):
        raise ValueError("invalid monitor job id")
    return _state_dir() / f"{job_id}.json"


def _empty_state() -> dict[str, Any]:
    return {
        "last_hash": None,
        "last_checked": None,
        "last_changed": None,
        "last_error": None,
    }


def load_state(job_id: str) -> dict[str, Any]:
    state = store._read_json(_state_path(job_id), {})
    if not isinstance(state, dict):
        state = {}
    return {**_empty_state(), **state}


def _save_state(job_id: str, state: dict[str, Any]) -> None:
    store._write_json(_state_path(job_id), state)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fetch_url(url: str, max_bytes: int) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("monitor URL must use HTTP or HTTPS")
    if _is_blocked_url(url):
        raise ValueError("refused blocked URL (SSRF guard)")

    request = urllib.request.Request(url, method="GET")
    # This handler re-runs the same SSRF validation for every redirect target.
    opener = urllib.request.build_opener(_GuardedRedirectHandler)
    with opener.open(request, timeout=30) as response:
        return response.read(max_bytes)


def _run_script(command: str) -> bytes:
    proc = subprocess.run(shell_argv(command), capture_output=True, timeout=600)
    stdout = proc.stdout or b""
    stderr = proc.stderr or b""
    if isinstance(stdout, str):
        stdout = stdout.encode("utf-8", "replace")
    if isinstance(stderr, str):
        stderr = stderr.encode("utf-8", "replace")
    content = stdout + stderr
    if proc.returncode != 0:
        raise RuntimeError(f"script exited with status {proc.returncode}")
    return content


def _acquire(job: dict[str, Any]) -> bytes:
    url = str(job.get("monitor_url") or "").strip()
    script = str(job.get("monitor_script") or "").strip()
    if bool(url) == bool(script):
        raise ValueError("monitor requires exactly one of monitor_url or monitor_script")
    if url:
        return _fetch_url(url, clamp_max_bytes(job.get("max_bytes")))
    return _run_script(script)


def _tail(content: bytes) -> str:
    return content.decode("utf-8", "replace")[-8000:]


def check(job: dict[str, Any]) -> MonitorResult:
    """Acquire one monitor source and compare it with the saved baseline.

    The first successful check establishes a baseline and is not a change.
    Acquisition failures update diagnostics only; they never replace the last
    successful hash and therefore can never manufacture a change event.
    """
    job_id = str(job.get("id") or "")
    state = load_state(job_id)
    checked = _now()
    try:
        content = _acquire(job)
    except Exception as exc:
        error = str(exc) or type(exc).__name__
        state["last_checked"] = checked
        state["last_error"] = error
        _save_state(job_id, state)
        return MonitorResult(False, error, "", "")

    current_hash = hashlib.sha256(content).hexdigest()
    previous_hash = state.get("last_hash")
    changed = previous_hash is not None and previous_hash != current_hash
    state["last_hash"] = current_hash
    state["last_checked"] = checked
    state["last_error"] = None
    if changed:
        state["last_changed"] = checked
    _save_state(job_id, state)

    context = ""
    if changed:
        context = (
            f"Previous SHA-256: {previous_hash}\n"
            f"Current SHA-256: {current_hash}"
        )[:4000]
    return MonitorResult(changed, None, context, _tail(content))
