"""Typed callable contracts shared by approval execution paths."""

from __future__ import annotations

from collections.abc import Callable
from typing import NewType, Protocol

from .approval_execution_codec import JSONValue

EventSink = Callable[..., None]
SealedApprovalId = NewType("SealedApprovalId", str)


class ActionExecutor(Protocol):
    def __call__(
        self,
        category: str,
        payload: dict[str, JSONValue],
        cfg: dict[str, JSONValue] | None = None,
        on_event: EventSink | None = None,
    ) -> str: ...
