"""CLI coverage for the ephemeral live-session inventory."""

from __future__ import annotations

from collections.abc import Iterable
from inspect import signature

import pytest

from birkin import (
    cli,
    live_process_source,
    live_sessions,
    sessions_export,
    sessions_index,
)
from birkin.live_process_source import ProcessHandle
from birkin.live_session_models import (
    LiveScan,
    RefusalCounts,
    ScanCounters,
)
from birkin.live_session_render import render_live_inventory

_CURRENT_USER = r"DOMAIN\lg"


class _IdleProcess:
    def __init__(self, pid: int) -> None:
        self._pid = pid

    def username(self) -> str:
        return _CURRENT_USER

    def pid(self) -> int:
        return self._pid

    def name(self) -> str:
        return "python.exe"

    def cmdline(self) -> str:
        return "python.exe harmless_script.py"

    def cwd(self) -> str:
        return r"C:\workspace"

    def open_files(self) -> tuple[str, ...]:
        return ()


class _FakeSource:
    def __init__(self, *processes: ProcessHandle) -> None:
        self._processes = processes

    def current_username(self) -> str:
        return _CURRENT_USER

    def processes(self) -> Iterable[ProcessHandle]:
        return self._processes


class _FailingSource(_FakeSource):
    def processes(self) -> Iterable[ProcessHandle]:
        raise OSError("access is denied")


def _counters(
    *,
    enumerated: int = 0,
    own_user: int = 0,
    unidentified: int = 0,
    cmdline_ok: int = 0,
    open_files_ok: int = 0,
    name: int = 0,
    cmdline: int = 0,
    cwd: int = 0,
    open_files: int = 0,
) -> ScanCounters:
    return ScanCounters(
        enumerated=enumerated,
        own_user=own_user,
        unidentified=unidentified,
        cmdline_ok=cmdline_ok,
        open_files_ok=open_files_ok,
        disappeared=0,
        refusals=RefusalCounts(
            name=name,
            cmdline=cmdline,
            cwd=cwd,
            open_files=open_files,
        ),
    )


def _install_source(
    monkeypatch: pytest.MonkeyPatch,
    source: _FakeSource,
) -> None:
    monkeypatch.setattr(
        live_process_source,
        "PsutilProcessSource",
        lambda: source,
    )


def test_sessions_live_dispatches_without_saved_session_index(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _FakeSource()
    _install_source(monkeypatch, source)
    scanned: list[object] = []

    def fake_scan(received: object) -> LiveScan:
        scanned.append(received)
        return LiveScan(processes=(), counters=_counters())

    monkeypatch.setattr(live_sessions, "scan_live_sessions", fake_scan)
    monkeypatch.setattr(
        sessions_export,
        "list_sessions",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("saved sessions must not be listed")
        ),
    )
    monkeypatch.setattr(
        sessions_export,
        "export",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("saved sessions must not be exported")
        ),
    )
    for operation in ("refresh", "search"):
        monkeypatch.setattr(
            sessions_index,
            operation,
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("saved sessions must not be indexed")
            ),
        )

    result = cli.main(["sessions", "live"])

    assert result == 0
    assert scanned == [source]
    assert capsys.readouterr().out.startswith("ACTIVE AGENT PROJECTS: 0\n")


def test_sessions_live_nothing_running_is_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _FakeSource(*(_IdleProcess(pid) for pid in range(1, 6)))
    _install_source(monkeypatch, source)

    result = cli.main(["sessions", "live"])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert captured.out == (
        "ACTIVE AGENT PROJECTS: 0\n"
        "No live agent sessions.\n"
        "SCAN: enumerated=5 own-user=5 unidentified=0 cmdline_ok=5 "
        "open_files_ok=5 disappeared=0\n"
        "REFUSALS: name=0 cmdline=0 cwd=0 open_files=0\n"
    )


def test_sessions_live_with_refusal_uses_counter_generated_limitation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _FakeSource()
    _install_source(monkeypatch, source)
    scans = iter(
        (
            LiveScan(
                processes=(),
                counters=_counters(
                    enumerated=1,
                    unidentified=1,
                    cmdline=2,
                    open_files=3,
                ),
            ),
            LiveScan(
                processes=(),
                counters=_counters(enumerated=1),
            ),
        )
    )
    monkeypatch.setattr(
        live_sessions,
        "scan_live_sessions",
        lambda received: next(scans),
    )

    assert cli.main(["sessions", "live"]) == 0
    with_refusal = capsys.readouterr().out
    assert (
        "LIMITATION: access is denied: cmdline=2 open_files=3\n"
    ) in with_refusal

    assert cli.main(["sessions", "live"]) == 0
    without_refusal = capsys.readouterr().out
    assert "LIMITATION:" not in without_refusal
    assert tuple(signature(render_live_inventory).parameters) == ("inventory",)


def test_sessions_live_rejects_extra_argument_before_scan(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _FakeSource()
    constructions: list[object] = []
    monkeypatch.setattr(
        live_process_source,
        "PsutilProcessSource",
        lambda: constructions.append(source) or source,
    )

    with pytest.raises(SystemExit) as stopped:
        cli.main(["sessions", "live", "unexpected"])

    captured = capsys.readouterr()
    assert stopped.value.code == 2
    assert captured.out == ""
    assert "unrecognized arguments: unexpected" in captured.err
    assert constructions == []


def test_sessions_unknown_names_valid_children(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _FakeSource()
    constructions: list[object] = []
    monkeypatch.setattr(
        live_process_source,
        "PsutilProcessSource",
        lambda: constructions.append(source) or source,
    )

    with pytest.raises(SystemExit) as stopped:
        cli.main(["sessions", "unknown"])

    captured = capsys.readouterr()
    assert stopped.value.code == 2
    assert captured.out == ""
    assert "unknown" in captured.err
    assert "export" in captured.err
    assert "live" in captured.err
    assert constructions == []


def test_source_wide_scan_failure_returns_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_source(monkeypatch, _FailingSource())

    result = cli.main(["sessions", "live"])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == (
        "live sessions: process enumeration failed: access is denied\n"
    )
