"""Scan and group live agent processes by their observed working directory."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import replace
from typing import TypeVar

import psutil

from .live_process_source import ProcessSource
from .live_session_models import (
    LiveAgentProcess,
    LiveInventory,
    LiveProject,
    LiveScan,
    LiveSessionFile,
    Observation,
    ProcessField,
    ReadFailure,
    RefusalCounts,
    ScanCounters,
)
from .operation_policy import is_permission_denial

T = TypeVar("T")

_AGENT_MARKERS = (
    "omo.js", "senpi", "codex.exe", "codex",
    "claude.exe", "claude", "birkin", "-m birkin",
)
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_OMO_SESSION = re.compile(
    r"(?:^|/)\.omo/senpi-task/logs/(?P<id>st_[^/]+)\.jsonl$",
    re.IGNORECASE,
)
_CODEX_SESSION = re.compile(
    rf"(?:^|/)\.codex/sessions/\d{{4}}/\d{{2}}/\d{{2}}/"
    rf"rollout-[^/]*-(?P<id>{_UUID})\.jsonl$",
    re.IGNORECASE,
)
_CLAUDE_SESSION = re.compile(
    rf"(?:^|/)\.claude/(?:projects/[^/]+|sessions)/"
    rf"(?P<id>{_UUID})\.jsonl$",
    re.IGNORECASE,
)
_GONE_ERRORS = (psutil.NoSuchProcess, psutil.ZombieProcess)
_READ_ERRORS = (psutil.Error, OSError)


def scan_live_sessions(source: ProcessSource) -> LiveScan:
    """Return reportable live agents after inspecting only current-user processes."""
    current_username = source.current_username()
    if not current_username:
        raise OSError("current username is unavailable")

    counts = {
        "enumerated": 0,
        "own_user": 0,
        "unidentified": 0,
        "cmdline_ok": 0,
        "open_files_ok": 0,
        "disappeared": 0,
    }
    refusals = {field: 0 for field in ProcessField if field is not ProcessField.USERNAME}
    processes: list[LiveAgentProcess] = []

    for handle in source.processes():
        counts["enumerated"] += 1
        try:
            username = handle.username()
        except _GONE_ERRORS:
            counts["disappeared"] += 1
            continue
        except _READ_ERRORS:
            counts["unidentified"] += 1
            continue

        if username is None:
            counts["unidentified"] += 1
            continue
        if not _same_username(username, current_username):
            continue
        counts["own_user"] += 1

        try:
            pid = handle.pid()
            name, name_denied = _observe(handle.name)
            if name_denied:
                refusals[ProcessField.NAME] += 1

            cmdline, cmdline_denied = _observe(handle.cmdline)
            if cmdline_denied:
                refusals[ProcessField.CMDLINE] += 1
            elif cmdline.failure is None:
                counts["cmdline_ok"] += 1

            cwd, cwd_denied = _observe(handle.cwd)
            if cwd_denied:
                refusals[ProcessField.CWD] += 1

            open_paths, open_files_denied = _observe(handle.open_files)
            if open_files_denied:
                refusals[ProcessField.OPEN_FILES] += 1
            elif open_paths.failure is None:
                counts["open_files_ok"] += 1
        except _GONE_ERRORS:
            counts["disappeared"] += 1
            continue

        session_files = _session_observation(open_paths)
        marker_seen = _agent_marker_seen(name, cmdline)
        mapped = session_files.value
        if not mapped and not (marker_seen and session_files.failure is not None):
            continue
        processes.append(
            LiveAgentProcess(
                pid=pid,
                name=name,
                cmdline=cmdline,
                cwd=cwd,
                session_files=session_files,
                agent_marker_seen=marker_seen,
            )
        )

    return LiveScan(
        processes=tuple(processes),
        counters=ScanCounters(
            enumerated=counts["enumerated"],
            own_user=counts["own_user"],
            unidentified=counts["unidentified"],
            cmdline_ok=counts["cmdline_ok"],
            open_files_ok=counts["open_files_ok"],
            disappeared=counts["disappeared"],
            refusals=RefusalCounts(
                name=refusals[ProcessField.NAME],
                cmdline=refusals[ProcessField.CMDLINE],
                cwd=refusals[ProcessField.CWD],
                open_files=refusals[ProcessField.OPEN_FILES],
            ),
        ),
    )


def group_live_sessions(scan: LiveScan) -> LiveInventory:
    """Group reportable processes using only successful cwd observations."""
    grouped: dict[str, tuple[str, list[LiveAgentProcess]]] = {}
    unknown: list[LiveAgentProcess] = []
    for original in scan.processes:
        process = _with_sorted_sessions(original)
        if process.cwd.value is None:
            unknown.append(process)
            continue
        identity = os.path.normpath(process.cwd.value)
        if os.name == "nt":
            identity = os.path.normcase(identity)
        if identity not in grouped:
            grouped[identity] = (process.cwd.value, [])
        grouped[identity][1].append(process)

    projects = tuple(
        LiveProject(
            cwd=cwd,
            processes=tuple(sorted(processes, key=lambda item: item.pid)),
        )
        for cwd, processes in sorted(
            grouped.values(),
            key=lambda item: item[0].casefold(),
        )
    )
    return LiveInventory(
        projects=projects,
        unknown_project=tuple(sorted(unknown, key=lambda item: item.pid)),
        counters=scan.counters,
    )


def _observe(reader: Callable[[], T]) -> tuple[Observation[T], bool]:
    try:
        return Observation(value=reader(), failure=None), False
    except _GONE_ERRORS:
        raise
    except _READ_ERRORS as exc:
        denied = _is_permission_denial(exc)
        failure = (
            ReadFailure.ACCESS_DENIED if denied else ReadFailure.UNAVAILABLE
        )
        return Observation(value=None, failure=failure), denied


def _is_permission_denial(exc: BaseException) -> bool:
    native_detail = f"{type(exc).__name__}: {exc}"
    return is_permission_denial(native_detail)


def _same_username(observed: str | None, current: str) -> bool:
    if observed is None:
        return False
    if os.name == "nt":
        return observed.casefold() == current.casefold()
    return observed == current


def _session_observation(
    paths: Observation[tuple[str, ...]],
) -> Observation[tuple[LiveSessionFile, ...]]:
    if paths.value is None:
        return Observation(value=None, failure=paths.failure)
    files = tuple(
        session
        for path in paths.value
        if (session := _session_from_path(path)) is not None
    )
    return Observation(
        value=tuple(sorted(files, key=lambda item: (item.session_id, item.path))),
        failure=None,
    )


def _session_from_path(path: str) -> LiveSessionFile | None:
    normalized = path.replace("\\", "/")
    for pattern in (_OMO_SESSION, _CODEX_SESSION, _CLAUDE_SESSION):
        match = pattern.search(normalized)
        if match is not None:
            return LiveSessionFile(session_id=match.group("id"), path=path)
    return None


def _agent_marker_seen(
    name: Observation[str],
    cmdline: Observation[str],
) -> bool:
    text = " ".join(
        value for value in (name.value, cmdline.value) if value is not None
    ).casefold()
    return any(marker in text for marker in _AGENT_MARKERS)


def _with_sorted_sessions(process: LiveAgentProcess) -> LiveAgentProcess:
    files = process.session_files.value
    if files is None:
        return process
    ordered = tuple(sorted(files, key=lambda item: (item.session_id, item.path)))
    return replace(
        process,
        session_files=Observation(value=ordered, failure=None),
    )
