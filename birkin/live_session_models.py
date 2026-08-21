"""Immutable value objects for live agent-session introspection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

T = TypeVar("T")


class ProcessField(Enum):
    USERNAME = "username"
    NAME = "name"
    CMDLINE = "cmdline"
    CWD = "cwd"
    OPEN_FILES = "open_files"


class ReadFailure(Enum):
    ACCESS_DENIED = "access_denied"
    UNAVAILABLE = "unavailable"
    PROCESS_GONE = "process_gone"


# Omit slots: Python 3.10 breaks subscripted construction of frozen Generic dataclasses.
@dataclass(frozen=True)
class Observation(Generic[T]):
    value: T | None
    failure: ReadFailure | None

    def __post_init__(self) -> None:
        if (self.value is None) == (self.failure is None):
            raise ValueError(
                "observation requires exactly one of value or failure"
            )


@dataclass(frozen=True, slots=True)
class LiveSessionFile:
    session_id: str
    path: str


@dataclass(frozen=True, slots=True)
class LiveAgentProcess:
    pid: int
    name: Observation[str]
    cmdline: Observation[str]
    cwd: Observation[str]
    session_files: Observation[tuple[LiveSessionFile, ...]]
    agent_marker_seen: bool


@dataclass(frozen=True, slots=True)
class RefusalCounts:
    name: int
    cmdline: int
    cwd: int
    open_files: int

    def __post_init__(self) -> None:
        if any(
            count < 0
            for count in (
                self.name,
                self.cmdline,
                self.cwd,
                self.open_files,
            )
        ):
            raise ValueError("refusal counts must be non-negative")

    @property
    def total(self) -> int:
        return self.name + self.cmdline + self.cwd + self.open_files

    def nonzero(self) -> tuple[tuple[ProcessField, int], ...]:
        counts = (
            (ProcessField.NAME, self.name),
            (ProcessField.CMDLINE, self.cmdline),
            (ProcessField.CWD, self.cwd),
            (ProcessField.OPEN_FILES, self.open_files),
        )
        return tuple(item for item in counts if item[1] != 0)


@dataclass(frozen=True, slots=True)
class ScanCounters:
    enumerated: int
    own_user: int
    unidentified: int
    cmdline_ok: int
    open_files_ok: int
    disappeared: int
    refusals: RefusalCounts

    def __post_init__(self) -> None:
        if any(
            count < 0
            for count in (
                self.enumerated,
                self.own_user,
                self.unidentified,
                self.cmdline_ok,
                self.open_files_ok,
                self.disappeared,
            )
        ):
            raise ValueError("scan counters must be non-negative")


@dataclass(frozen=True, slots=True)
class LiveScan:
    processes: tuple[LiveAgentProcess, ...]
    counters: ScanCounters


@dataclass(frozen=True, slots=True)
class LiveProject:
    cwd: str
    processes: tuple[LiveAgentProcess, ...]


@dataclass(frozen=True, slots=True)
class LiveInventory:
    projects: tuple[LiveProject, ...]
    unknown_project: tuple[LiveAgentProcess, ...]
    counters: ScanCounters
