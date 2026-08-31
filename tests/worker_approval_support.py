"""Typed support for worker approval end-to-end tests."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Protocol

from birkin import store
from birkin.tools._types import ToolContext
from birkin.worker_request_boundary import object_fields


class RunResult(Protocol):
    @property
    def stdout(self) -> str: ...

    @property
    def stderr(self) -> str: ...

    @property
    def returncode(self) -> int: ...


class Run(Protocol):
    def __call__(
        self,
        argv: tuple[str, ...],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
        shell: bool,
    ) -> RunResult: ...


@dataclass(frozen=True, slots=True)
class FakeSubprocess:
    run: Run
    TimeoutExpired: ClassVar[type[subprocess.TimeoutExpired]] = (
        subprocess.TimeoutExpired
    )


@dataclass(frozen=True, slots=True)
class FakeRunResult:
    stdout: str
    stderr: str
    returncode: int


def context(cwd: Path) -> ToolContext:
    return ToolContext(
        cfg={"auto_approve": ["shell"]},
        client=None,
        cwd=cwd,
    )


def mapping(value: object, label: str) -> Mapping[str, object]:
    return object_fields(value, label=label)


def text(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str):
        raise AssertionError(f"{key} must be text")
    return value


def pending(index: int = 0) -> Mapping[str, object]:
    records = store.list_pending()
    if len(records) <= index:
        raise AssertionError("expected a pending worker approval")
    return records[index]
