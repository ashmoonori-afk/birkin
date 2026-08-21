"""Live agent-session scanning, grouping, and rendering tests."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypeVar

import psutil

from birkin.live_process_source import ProcessHandle
from birkin.live_session_models import ReadFailure
from birkin.live_session_render import render_live_inventory
from birkin.live_sessions import group_live_sessions, scan_live_sessions

T = TypeVar("T")

_CURRENT_USER = r"DOMAIN\lg"
_OMO_PATH = (
    r"C:\workspace\.omo\senpi-task\logs\st_01a0222b.jsonl"
)
_CODEX_UUID = "01a021f3-711f-7621-8100-2dacdd7503e1"
_CODEX_PATH = (
    r"C:\Users\lg\.codex\sessions\2026\08\21"
    rf"\rollout-2026-08-21T10-33-22-{_CODEX_UUID}.jsonl"
)


def _result(value: T | BaseException) -> T:
    if isinstance(value, BaseException):
        raise value
    return value


class _FakeProcess:
    def __init__(
        self,
        *,
        pid: int = 100,
        username: str | None | BaseException = _CURRENT_USER,
        name: str | BaseException = "node.exe",
        cmdline: str | BaseException = "node.exe C:\\tools\\omo.js",
        cwd: str | BaseException = r"C:\workspace",
        open_files: tuple[str, ...] | BaseException = (_OMO_PATH,),
    ) -> None:
        self._pid = pid
        self._username = username
        self._name = name
        self._cmdline = cmdline
        self._cwd = cwd
        self._open_files = open_files
        self.calls: list[str] = []

    def username(self) -> str | None:
        self.calls.append("username")
        return _result(self._username)

    def pid(self) -> int:
        self.calls.append("pid")
        return self._pid

    def name(self) -> str:
        self.calls.append("name")
        return _result(self._name)

    def cmdline(self) -> str:
        self.calls.append("cmdline")
        return _result(self._cmdline)

    def cwd(self) -> str:
        self.calls.append("cwd")
        return _result(self._cwd)

    def open_files(self) -> tuple[str, ...]:
        self.calls.append("open_files")
        return _result(self._open_files)


class _FakeSource:
    def __init__(
        self,
        *processes: ProcessHandle,
        current_username: str = _CURRENT_USER,
    ) -> None:
        self._processes = processes
        self._current_username = current_username

    def current_username(self) -> str:
        return self._current_username

    def processes(self) -> Iterable[ProcessHandle]:
        return self._processes


class _ForeignUsernameOnlyProcess:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def username(self) -> str:
        self.calls.append("username")
        return "otherlg"

    def pid(self) -> int:
        raise AssertionError("pid must not be read for a foreign process")

    def name(self) -> str:
        raise AssertionError("name must not be read for a foreign process")

    def cmdline(self) -> str:
        raise AssertionError("cmdline must not be read for a foreign process")

    def cwd(self) -> str:
        raise AssertionError("cwd must not be read for a foreign process")

    def open_files(self) -> tuple[str, ...]:
        raise AssertionError("open files must not be read for a foreign process")


def test_zero_refusal_scan_emits_no_limitation_text() -> None:
    inventory = group_live_sessions(
        scan_live_sessions(_FakeSource(_FakeProcess()))
    )

    output = render_live_inventory(inventory)

    assert inventory.counters.refusals.total == 0
    assert not any(
        line.startswith("LIMITATION:") for line in output.splitlines()
    )
    assert "Windows 권한 제한" not in output
    assert "No permission limitation" not in output


def test_access_denied_is_counted_and_named() -> None:
    process = _FakeProcess(
        name="codex.exe",
        cmdline=psutil.AccessDenied(pid=100),
        open_files=(_CODEX_PATH,),
    )
    inventory = group_live_sessions(
        scan_live_sessions(_FakeSource(process))
    )

    output = render_live_inventory(inventory)

    assert len(inventory.projects[0].processes) == 1
    assert inventory.counters.refusals.cmdline == 1
    assert "access is denied" in output
    assert "cmdline=1" in output


def test_session_file_maps_one_to_one_to_session_id() -> None:
    shared_files = tuple(
        rf"C:\Users\lg\.codex\{name}_1.sqlite"
        for name in ("state", "logs", "goals", "memories")
    )
    process = _FakeProcess(
        name="codex.exe",
        cmdline="codex.exe exec",
        open_files=(_CODEX_PATH, *shared_files),
    )

    scan = scan_live_sessions(_FakeSource(process))

    session_files = scan.processes[0].session_files.value
    assert session_files is not None
    assert len(session_files) == 1
    assert session_files[0].path == _CODEX_PATH
    assert session_files[0].session_id == _CODEX_UUID
    assert not any(path in session_files[0].path for path in shared_files)


def test_omo_st_filename_maps_to_full_st_id() -> None:
    scan = scan_live_sessions(_FakeSource(_FakeProcess()))

    session_files = scan.processes[0].session_files.value
    assert session_files is not None
    assert session_files[0].session_id == "st_01a0222b"
    assert session_files[0].path == _OMO_PATH


def test_per_process_failure_degrades_one_entry_without_aborting_scan() -> None:
    first = _FakeProcess(
        pid=101,
        name=OSError("native name lookup failed"),
    )
    second = _FakeProcess(
        pid=202,
        name="codex.exe",
        cmdline="codex.exe exec",
        cwd=r"C:\second",
        open_files=(_CODEX_PATH,),
    )

    scan = scan_live_sessions(_FakeSource(first, second))

    assert [process.pid for process in scan.processes] == [101, 202]
    assert scan.processes[0].name.failure is ReadFailure.UNAVAILABLE
    assert scan.processes[0].session_files.value is not None
    assert scan.processes[0].session_files.value[0].session_id == "st_01a0222b"
    assert scan.counters.enumerated == 2


def test_foreign_process_is_filtered_before_any_other_read() -> None:
    foreign = _ForeignUsernameOnlyProcess()

    scan = scan_live_sessions(
        _FakeSource(foreign, current_username="lg")
    )

    assert scan.processes == ()
    assert scan.counters.enumerated == 1
    assert scan.counters.own_user == 0
    assert foreign.calls == ["username"]


def test_unidentified_processes_do_not_produce_a_limitation() -> None:
    unidentified = tuple(
        _FakeProcess(
            pid=pid,
            username=psutil.AccessDenied(pid=pid),
        )
        for pid in range(10, 20)
    )
    healthy = _FakeProcess(pid=100)

    inventory = group_live_sessions(
        scan_live_sessions(_FakeSource(*unidentified, healthy))
    )
    output = render_live_inventory(inventory)

    assert len(inventory.projects[0].processes) == 1
    assert inventory.counters.unidentified == len(unidentified)
    assert inventory.counters.refusals.total == 0
    assert not any(
        line.startswith("LIMITATION:") for line in output.splitlines()
    )


def test_username_access_denied_does_not_claim_current_user_scope() -> None:
    process = _FakeProcess(username=psutil.AccessDenied(pid=100))

    inventory = group_live_sessions(
        scan_live_sessions(_FakeSource(process))
    )
    output = render_live_inventory(inventory)

    assert inventory.counters.own_user == 0
    assert inventory.counters.unidentified == 1
    assert inventory.counters.refusals.total == 0
    assert process.calls == ["username"]
    assert "own-user=0 unidentified=1" in output
    assert not any(
        line.startswith("LIMITATION:") for line in output.splitlines()
    )


def test_cwd_access_denied_retains_session_under_unknown_project() -> None:
    process = _FakeProcess(cwd=psutil.AccessDenied(pid=100))

    inventory = group_live_sessions(
        scan_live_sessions(_FakeSource(process))
    )
    output = render_live_inventory(inventory)

    assert inventory.projects == ()
    assert len(inventory.unknown_project) == 1
    assert inventory.counters.refusals.cwd == 1
    assert "st_01a0222b" in output
    assert r"PROJECT: C:\workspace" not in output


def test_confirmed_owner_refusal_still_produces_a_limitation() -> None:
    process = _FakeProcess(cwd=psutil.AccessDenied(pid=100))

    inventory = group_live_sessions(
        scan_live_sessions(_FakeSource(process))
    )
    output = render_live_inventory(inventory)

    assert inventory.counters.refusals.cwd == 1
    assert "LIMITATION: access is denied: cwd=1" in output


def test_grouping_uses_cwd_not_codex_session_parent() -> None:
    first = _FakeProcess(
        pid=10,
        name="codex.exe",
        cmdline="codex.exe exec one",
        cwd=r"C:\project-one",
        open_files=(_CODEX_PATH,),
    )
    second_path = _CODEX_PATH.replace(_CODEX_UUID, (
        "02b132f4-822f-8732-9211-3ebcee8614f2"
    ))
    second = _FakeProcess(
        pid=20,
        name="codex.exe",
        cmdline="codex.exe exec two",
        cwd=r"C:\project-two",
        open_files=(second_path,),
    )

    inventory = group_live_sessions(
        scan_live_sessions(_FakeSource(first, second))
    )

    assert [project.cwd for project in inventory.projects] == [
        r"C:\project-one",
        r"C:\project-two",
    ]
    assert all(len(project.processes) == 1 for project in inventory.projects)


def test_process_disappearance_does_not_abort_remaining_scan() -> None:
    disappeared = _FakeProcess(
        pid=10,
        name=psutil.NoSuchProcess(pid=10),
    )
    healthy = _FakeProcess(pid=20)

    scan = scan_live_sessions(_FakeSource(disappeared, healthy))

    assert [process.pid for process in scan.processes] == [20]
    assert scan.counters.disappeared == 1
    assert scan.counters.refusals.total == 0


def test_renderer_does_not_truncate_commandline() -> None:
    final_token = "unique-final-token-that-must-survive-rendering"
    command = "codex.exe exec " + "x" * 180 + " " + final_token
    process = _FakeProcess(
        name="codex.exe",
        cmdline=command,
        open_files=(_CODEX_PATH,),
    )
    inventory = group_live_sessions(
        scan_live_sessions(_FakeSource(process))
    )

    output = render_live_inventory(inventory)

    assert final_token in output
    assert command in output
