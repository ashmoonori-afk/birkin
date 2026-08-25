from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from birkin.executable_resolution import (
    CommandProbe,
    EnvironmentPathCandidates,
    ExecutableResolver,
    ProbeExecution,
    ProbeFailureKind,
)


@dataclass
class FakeCandidates:
    by_command: dict[str, tuple[str, ...]]

    def candidates(self, command: str) -> tuple[str, ...]:
        return self.by_command.get(command, ())


@dataclass
class FakeRunner:
    executions: dict[str, ProbeExecution]
    probed: list[CommandProbe] = field(default_factory=list)

    def run(self, probe: CommandProbe) -> ProbeExecution:
        self.probed.append(probe)
        return self.executions[probe.path]


def _python_resolver(
    paths: tuple[str, ...],
    executions: dict[str, ProbeExecution],
) -> tuple[ExecutableResolver, FakeRunner]:
    candidates = FakeCandidates({"python": paths})
    runner = FakeRunner(executions)
    return ExecutableResolver(candidates, runner, python_fallback=None), runner


def test_do_nothing_shim_ahead_on_path_is_rejected() -> None:
    shim = r"C:\WindowsApps\shim-python.exe"
    real = r"C:\Python312\real-python.exe"
    resolver, runner = _python_resolver(
        (shim, real),
        {
            shim: ProbeExecution(9009, "", "Python "),
            real: ProbeExecution(0, "birkin-python-probe-v1", ""),
        },
    )

    resolution = resolver.resolve_python()

    assert resolution.usable is True
    assert resolution.selected_path == real
    assert resolution.attempts[0].failure_kind is ProbeFailureKind.NON_FUNCTIONAL_SHIM
    assert [probe.path for probe in runner.probed] == [shim, real]


def test_only_shim_failure_names_exact_path() -> None:
    shim = r"C:\Users\lg\AppData\Local\Microsoft\WindowsApps\python.exe"
    resolver, _ = _python_resolver(
        (shim,),
        {shim: ProbeExecution(9009, "", "Python ")},
    )

    resolution = resolver.resolve_python()
    diagnostic = resolution.failure_text()

    assert resolution.usable is False
    assert f"resolved to a non-functional shim at {shim}" in diagnostic
    assert "exit 9009" in diagnostic
    assert 'stderr "Python "' in diagnostic
    assert "not installed" not in diagnostic


def test_python_probe_requires_exact_sentinel() -> None:
    empty = r"C:\bin\empty.exe"
    wrong = r"C:\bin\wrong.exe"
    exact = r"C:\bin\exact.exe"
    resolver, _ = _python_resolver(
        (empty, wrong, exact),
        {
            empty: ProbeExecution(0, "", ""),
            wrong: ProbeExecution(0, "Python ", ""),
            exact: ProbeExecution(0, "birkin-python-probe-v1", ""),
        },
    )

    resolution = resolver.resolve_python()

    assert [attempt.failure_kind for attempt in resolution.attempts] == [
        ProbeFailureKind.NON_FUNCTIONAL_SHIM,
        ProbeFailureKind.NON_FUNCTIONAL_SHIM,
        None,
    ]
    assert resolution.selected_path == exact


def test_no_candidate_reports_path_lookup_reason() -> None:
    resolver, _ = _python_resolver((), {})

    resolution = resolver.resolve_python()

    assert resolution.usable is False
    assert resolution.failure_text() == (
        "python: no executable candidate was found on PATH"
    )


def test_probe_timeout_is_typed_without_waiting() -> None:
    path = r"C:\bin\python.exe"

    class TimeoutRunner:
        def run(self, probe: CommandProbe) -> ProbeExecution:
            raise subprocess.TimeoutExpired(probe.path, probe.timeout_seconds)

    resolver = ExecutableResolver(
        FakeCandidates({"python": (path,)}),
        TimeoutRunner(),
        python_fallback=None,
    )

    resolution = resolver.resolve_python()

    assert resolution.attempts[0].failure_kind is ProbeFailureKind.TIMED_OUT
    assert resolution.failure_text() == (
        f"python: probe timed out for executable at {path}"
    )


def test_path_candidates_preserve_directory_order(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    first_exe = first / "tool.EXE"
    second_exe = second / "tool.EXE"
    first_exe.write_bytes(b"")
    second_exe.write_bytes(b"")
    source = EnvironmentPathCandidates(
        path=f"{first};{second}",
        pathext=".EXE;.CMD",
        windows=True,
    )

    assert source.candidates("tool") == (str(first_exe), str(second_exe))


@pytest.mark.parametrize("path_value", ["relative-bin", ""])
def test_path_candidates_reject_relative_and_empty_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path_value: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "relative-bin"
    directory.mkdir()
    executable = directory / "tool"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    if path_value == "":
        cwd_executable = tmp_path / "tool"
        cwd_executable.write_text("#!/bin/sh\n", encoding="utf-8")
        cwd_executable.chmod(0o700)

    source = EnvironmentPathCandidates(
        path=path_value,
        pathext="",
        windows=False,
    )

    assert source.candidates("tool") == ()
