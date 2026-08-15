"""Orphan-process reaper for birkin-spawned warm CLI subprocesses.

A warm :class:`~birkin.claude_session.ClaudeStreamSession` /
:class:`~birkin.codex_session.CodexAppServerSession` spawns ``claude`` /
``codex``, which run **node**. If the birkin process that owns them dies
ungracefully (SIGKILL, power loss, an unhandled crash before ``_terminate``),
those node trees keep running as orphans — nothing reaps them, and they
accumulate one per abandoned session.

Design (safe by construction):
  - Each birkin process records the child PIDs it spawns in a *per-owner*
    file ``~/.birkin/runs/procreg-<owner_pid>.json``.
  - The hourly reaper (driven by the scheduler daemon) reads every such file
    and kills the children **only when their owner process is gone**. A live
    birkin's sessions are never touched.

The worst case is therefore leaving an orphan one extra hour — never killing
a process a live birkin is still using. Pure stdlib; no psutil.
"""

from __future__ import annotations

import atexit
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import config, store
from .proc import kill_process_group

_atexit_armed = False


def _runs_dir() -> Path:
    d = config.birkin_home() / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _reg_path(owner: int | None = None) -> Path:
    return _runs_dir() / f"procreg-{owner or os.getpid()}.json"


def pid_alive(pid: int | None) -> bool:
    """True if ``pid`` names a live process. Cross-platform, stdlib only.

    Windows note: a process that exits with the exact code 259 is
    indistinguishable from STILL_ACTIVE via GetExitCodeProcess; 259 is a rare
    exit code, and the failure mode is conservative (we'd *skip* reaping, not
    kill a live one)."""
    if not pid or int(pid) <= 0:
        return False
    pid = int(pid)
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k = ctypes.windll.kernel32
        h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if not k.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # exists, just not ours to signal
    except OSError:
        return False
    return True


def _kill_pid(pid: int) -> None:
    """Kill a PID and its descendants (the claude/codex -> node tree).
    Best-effort: never raises."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=10)
        else:
            import signal as _sig
            if not kill_process_group(int(pid)):
                os.kill(int(pid), _sig.SIGTERM)
    except Exception:
        pass


def register(child_pid: int, owner: int | None = None) -> None:
    """Record ``child_pid`` under this process so a later reaper can find it
    if we die ungracefully. Also arms an atexit cleanup on first use."""
    global _atexit_armed
    if not child_pid:
        return
    p = _reg_path(owner)
    try:
        with store.file_lock(p):
            raw = store._read_json(p, None)
            data: dict[str, object] = (
                raw if isinstance(raw, dict) else {
                    "owner": owner or os.getpid(),
                    "children": [],
                }
            )
            existing = data.get("children")
            children = (
                [
                    value
                    for value in existing
                    if isinstance(value, int) and not isinstance(value, bool)
                ]
                if isinstance(existing, list)
                else []
            )
            if child_pid not in children:
                children.append(child_pid)
            data["children"] = children
            data["updated"] = datetime.now().isoformat(timespec="seconds")
            store._write_json(p, data)
    except store.FileLockTimeout:
        return
    if not _atexit_armed:
        atexit.register(cleanup_self)
        _atexit_armed = True


def unregister(child_pid: int, owner: int | None = None) -> None:
    """Drop ``child_pid`` after a graceful terminate; remove the file when the
    last child is gone."""
    if not child_pid:
        return
    p = _reg_path(owner)
    try:
        with store.file_lock(p):
            raw = store._read_json(p, None)
            if not isinstance(raw, dict):
                return
            data: dict[str, object] = raw
            existing = data.get("children")
            children = (
                [
                    value
                    for value in existing
                    if isinstance(value, int)
                    and not isinstance(value, bool)
                    and value != child_pid
                ]
                if isinstance(existing, list)
                else []
            )
            data["children"] = children
            if children:
                store._write_json(p, data)
            else:
                try:
                    p.unlink()
                except OSError:
                    pass
    except store.FileLockTimeout:
        return


def cleanup_self() -> None:
    """Remove this process's registry file on a graceful exit (atexit)."""
    try:
        _reg_path().unlink()
    except OSError:
        pass


def reap_orphans(*, alive: Callable[[int | None], bool] = pid_alive,
                 kill: Callable[[int], None] = _kill_pid) -> dict[str, Any]:
    """Kill children of any registry whose OWNER process is gone, then delete
    that registry. Live owners are skipped entirely. Returns a summary."""
    killed = 0
    dead_owners = 0
    for f in sorted(_runs_dir().glob("procreg-*.json")):
        data = store._read_json(f, None)
        if not isinstance(data, dict):
            try:
                f.unlink()          # corrupt/empty — clear it
            except OSError:
                pass
            continue
        if alive(data.get("owner")):
            continue                # a live birkin owns these — hands off
        dead_owners += 1
        for child in data.get("children", []):
            if alive(child):
                kill(child)
                killed += 1
        try:
            f.unlink()
        except OSError:
            pass
    return {"dead_owners": dead_owners, "killed": killed}
