"""Typed structural adapters for untrusted JSON-like values."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Protocol, runtime_checkable

from .worker_request_models import WorkerRequestError


@runtime_checkable
class _ObjectItems(Protocol):
    def items(self) -> Iterable[tuple[object, object]]: ...


@runtime_checkable
class _ObjectList(Protocol):
    def __iter__(self) -> Iterator[object]: ...
    def append(self, value: object) -> None: ...


def object_fields(value: object, *, label: str = "request") -> dict[str, object]:
    if not isinstance(value, _ObjectItems):
        raise WorkerRequestError(f"{label} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise WorkerRequestError(f"{label} field names must be text")
        result[key] = item
    return result


def object_list(value: object, *, label: str) -> tuple[object, ...]:
    if not isinstance(value, _ObjectList):
        raise WorkerRequestError(f"{label} must be a list")
    return tuple(value)
