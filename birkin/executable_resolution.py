"""Resolve executable candidates by verifying their behavior through execution."""

from __future__ import annotations

import json
import ntpath
import os
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol, final

_PYTHON_SENTINEL = "birkin-python-probe-v1"
_PYTHON_CODE = f"import sys; sys.stdout.write({_PYTHON_SENTINEL!r})"


class OutputMatch(Enum):
    EXACT_STDOUT = "exact_stdout"
    NONEMPTY_VERSION_OUTPUT = "nonempty_version_output"


class ProbeFailureKind(Enum):
    NON_FUNCTIONAL_SHIM = "non_functional_shim"
    START_FAILED = "start_failed"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class ProbeExpectation:
    output_match: OutputMatch
    expected_stdout: str = ""

@dataclass(frozen=True, slots=True)
class CommandProbe:
    command: str
    path: str
    arguments: tuple[str, ...]
    expectation: ProbeExpectation
    timeout_seconds: float = 5.0

@dataclass(frozen=True, slots=True)
class ProbeExecution:
    returncode: int
    stdout: str
    stderr: str

@dataclass(frozen=True, slots=True)
class ProbeAttempt:
    path: str
    execution: ProbeExecution | None
    failure_kind: ProbeFailureKind | None
    native_error: str | None = None

@dataclass(frozen=True, slots=True)
class CommandResolution:
    command: str
    selected_path: str | None
    attempts: tuple[ProbeAttempt, ...]
    expectation: ProbeExpectation

    @property
    def usable(self) -> bool:
        return self.selected_path is not None

    def failure_text(self) -> str:
        if self.usable:
            return ""
        if not self.attempts:
            return f"{self.command}: no executable candidate was found on PATH"
        attempt = self.attempts[0]
        if attempt.failure_kind is ProbeFailureKind.START_FAILED:
            return (
                f"{self.command}: executable at {attempt.path} could not be "
                f"started: {attempt.native_error}"
            )
        if attempt.failure_kind is ProbeFailureKind.TIMED_OUT:
            return f"{self.command}: probe timed out for executable at {attempt.path}"
        execution = attempt.execution
        assert execution is not None
        expected = self.expectation.expected_stdout
        return (
            f"{self.command}: resolved to a non-functional shim at {attempt.path} "
            f"(exit {execution.returncode}; expected stdout "
            f"{json.dumps(expected)}; stderr {json.dumps(execution.stderr)})"
        )


class ExecutableCandidates(Protocol):
    def candidates(self, command: str) -> tuple[str, ...]: ...

class ProbeRunner(Protocol):
    def run(self, probe: CommandProbe) -> ProbeExecution: ...

@final
class EnvironmentPathCandidates:
    def __init__(
        self,
        *,
        path: str | None = None,
        pathext: str | None = None,
        windows: bool | None = None,
    ) -> None:
        self._windows = os.name == "nt" if windows is None else windows
        self._path = os.environ.get("PATH", "") if path is None else path
        self._pathext = (
            os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD")
            if pathext is None
            else pathext
        )

    def candidates(self, command: str) -> tuple[str, ...]:
        separator = ";" if self._windows else os.pathsep
        directories = self._path.split(separator)
        extensions = self._extensions(command)
        found: list[str] = []
        seen: set[str] = set()
        for raw_directory in directories:
            directory = raw_directory.strip().strip('"')
            if not directory:
                continue
            if self._windows:
                drive, tail = ntpath.splitdrive(directory)
                is_absolute = (
                    bool(drive) and tail.startswith(("\\", "/"))
                ) or Path(directory).is_absolute()
            else:
                is_absolute = Path(directory).is_absolute()
            if not is_absolute:
                continue
            for extension in extensions:
                candidate = Path(directory) / f"{command}{extension}"
                if not candidate.is_file():
                    continue
                if not self._windows and not os.access(candidate, os.X_OK):
                    continue
                reportable = str(candidate)
                key = os.path.normcase(os.path.abspath(reportable))
                if key not in seen:
                    seen.add(key)
                    found.append(reportable)
        return tuple(found)
    def _extensions(self, command: str) -> tuple[str, ...]:
        if not self._windows:
            return ("",)
        extensions = tuple(
            item if item.startswith(".") else f".{item}"
            for item in self._pathext.split(";")
            if item
        )
        if Path(command).suffix.lower() in {item.lower() for item in extensions}:
            return ("",)
        return extensions

@final
class SubprocessProbeRunner:
    def run(self, probe: CommandProbe) -> ProbeExecution:
        completed = subprocess.run(
            [probe.path, *probe.arguments],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=probe.timeout_seconds,
            check=False,
        )
        return ProbeExecution(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

@final
class ExecutableResolver:
    def __init__(
        self,
        candidates: ExecutableCandidates | None = None,
        runner: ProbeRunner | None = None,
        *,
        python_fallback: str | None = sys.executable,
    ) -> None:
        self._candidates = candidates or EnvironmentPathCandidates()
        self._runner = runner or SubprocessProbeRunner()
        self._python_fallback = python_fallback

    def resolve_python(self) -> CommandResolution:
        paths: list[str] = []
        for command in ("python", "python3", "py"):
            paths.extend(self._candidates.candidates(command))
        if self._python_fallback:
            paths.append(self._python_fallback)
        expectation = ProbeExpectation(OutputMatch.EXACT_STDOUT, _PYTHON_SENTINEL)
        return self._resolve_paths(
            "python",
            paths,
            ("-c", _PYTHON_CODE),
            expectation,
        )

    def resolve(self, command: str) -> CommandResolution:
        expectation = ProbeExpectation(OutputMatch.NONEMPTY_VERSION_OUTPUT)
        return self._resolve_paths(
            command,
            list(self._candidates.candidates(command)),
            ("--version",),
            expectation,
        )

    def _resolve_paths(
        self,
        command: str,
        paths: list[str],
        arguments: tuple[str, ...],
        expectation: ProbeExpectation,
    ) -> CommandResolution:
        attempts: list[ProbeAttempt] = []
        for path in _dedupe_paths(paths):
            probe = CommandProbe(command, path, arguments, expectation)
            try:
                execution = self._runner.run(probe)
            except subprocess.TimeoutExpired:
                attempts.append(ProbeAttempt(
                    path, None, ProbeFailureKind.TIMED_OUT,
                ))
                continue
            except OSError as error:
                attempts.append(ProbeAttempt(
                    path, None, ProbeFailureKind.START_FAILED, str(error),
                ))
                continue
            if _matches(execution, expectation):
                attempts.append(ProbeAttempt(path, execution, None))
                return CommandResolution(command, path, tuple(attempts), expectation)
            attempts.append(ProbeAttempt(
                path, execution, ProbeFailureKind.NON_FUNCTIONAL_SHIM,
            ))
        return CommandResolution(command, None, tuple(attempts), expectation)


def _matches(execution: ProbeExecution, expectation: ProbeExpectation) -> bool:
    if execution.returncode != 0:
        return False
    if expectation.output_match is OutputMatch.EXACT_STDOUT:
        return execution.stdout == expectation.expected_stdout
    return bool(execution.stdout or execution.stderr)


def _dedupe_paths(paths: list[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return tuple(unique)
