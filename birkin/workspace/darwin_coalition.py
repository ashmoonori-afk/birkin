"""Kernel resource-coalition cleanup for Darwin process trees."""

from __future__ import annotations

import ctypes
import os
import select
import signal
import time
from typing import cast, final

_PROC_PIDCOALITIONINFO = 20
_COALITION_TYPE_RESOURCE = 0
_KQ_NOTE_SIGNAL = 0x08000000
_CLEANUP_TIMEOUT_SECONDS = 5.0


@final
class _ProcessCoalitionInfo(ctypes.Structure):
    _fields_ = [
        ("coalition_id", ctypes.c_uint64 * 2),
        ("reserved1", ctypes.c_uint64),
        ("reserved2", ctypes.c_uint64),
        ("reserved3", ctypes.c_uint64),
    ]


@final
class DarwinCoalitionCleanupError(RuntimeError):
    """Raised when a Darwin resource coalition cannot be emptied."""


def resource_coalition_id(pid: int) -> int | None:
    """Return the kernel resource-coalition identifier for one process."""
    info = _ProcessCoalitionInfo()
    received = cast(
        int,
        _libproc().proc_pidinfo(
            pid,
            _PROC_PIDCOALITIONINFO,
            0,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ),
    )
    if received != ctypes.sizeof(info):
        return None
    coalition_id = cast(
        int,
        info.coalition_id[_COALITION_TYPE_RESOURCE],
    )
    return coalition_id


def terminate_resource_coalition(coalition_id: int) -> None:
    """Quiesce and kill every live member of a resource coalition."""
    deadline = time.monotonic() + _CLEANUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        members = _coalition_members(coalition_id)
        if not members:
            return
        stopped = _quiesce_coalition(coalition_id, deadline=deadline)
        _kill_and_wait(coalition_id, stopped, deadline=deadline)
    survivors = _coalition_members(coalition_id)
    raise DarwinCoalitionCleanupError(
        f"terminal coalition still owns {len(survivors)} processes"
    )


def _quiesce_coalition(
    coalition_id: int,
    *,
    deadline: float,
) -> tuple[int, ...]:
    stopped: set[int] = set()
    while time.monotonic() < deadline:
        members = set(_coalition_members(coalition_id))
        if members <= stopped:
            return tuple(members)
        pending = members - stopped
        queue = select.kqueue()
        watched: set[int] = set()
        try:
            for pid in pending:
                try:
                    _ = queue.control(
                        [select.kevent(
                            pid,
                            filter=select.KQ_FILTER_PROC,
                            flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                            fflags=_KQ_NOTE_SIGNAL,
                        )],
                        0,
                        0,
                    )
                except OSError:
                    continue
                watched.add(pid)
            for pid in tuple(watched):
                if resource_coalition_id(pid) != coalition_id:
                    watched.discard(pid)
                    continue
                try:
                    os.kill(pid, signal.SIGSTOP)
                except ProcessLookupError:
                    watched.discard(pid)
            while watched:
                remaining = max(0.0, deadline - time.monotonic())
                if remaining == 0:
                    break
                events = queue.control(None, len(watched), remaining)
                if not events:
                    break
                signalled = {int(event.ident) for event in events}
                stopped.update(signalled)
                watched.difference_update(signalled)
        finally:
            queue.close()
    survivors = _coalition_members(coalition_id)
    raise DarwinCoalitionCleanupError(
        f"terminal coalition quiescence left {len(survivors)} processes"
    )


def _kill_and_wait(
    coalition_id: int,
    members: tuple[int, ...],
    *,
    deadline: float,
) -> None:
    queue = select.kqueue()
    watched: set[int] = set()
    try:
        for pid in members:
            try:
                _ = queue.control(
                    [select.kevent(
                        pid,
                        filter=select.KQ_FILTER_PROC,
                        flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                        fflags=select.KQ_NOTE_EXIT,
                    )],
                    0,
                    0,
                )
            except OSError:
                continue
            watched.add(pid)
        for pid in tuple(watched):
            if resource_coalition_id(pid) != coalition_id:
                watched.discard(pid)
                continue
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                watched.discard(pid)
        while watched:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining == 0:
                return
            events = queue.control(None, len(watched), remaining)
            if not events:
                return
            watched.difference_update(int(event.ident) for event in events)
    finally:
        queue.close()


def _coalition_members(coalition_id: int) -> tuple[int, ...]:
    library = _libproc()
    count = cast(int, library.proc_listallpids(None, 0))
    if count <= 0:
        raise DarwinCoalitionCleanupError("process enumeration failed")
    pids: ctypes.Array[ctypes.c_int] = (ctypes.c_int * count)()
    received = cast(
        int,
        library.proc_listallpids(pids, ctypes.sizeof(pids)),
    )
    if received < 0:
        raise DarwinCoalitionCleanupError("process enumeration failed")
    members: list[int] = []
    for index in range(received):
        pid = cast(int, pids[index])
        if pid > 0 and resource_coalition_id(pid) == coalition_id:
            members.append(pid)
    return tuple(members)


def _libproc() -> ctypes.CDLL:
    library = ctypes.CDLL(None, use_errno=True)
    library.proc_pidinfo.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    ]
    library.proc_pidinfo.restype = ctypes.c_int
    library.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
    library.proc_listallpids.restype = ctypes.c_int
    return library
