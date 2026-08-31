"""Shared outbound channel registry contracts."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from urllib.request import Request
from typing import Protocol, TypeAlias


JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
Config: TypeAlias = dict[str, JsonValue]


class WebhookResponse(Protocol):
    """The response operations used by standard-library webhook delivery."""

    status: int

    def read(self) -> bytes: ...


class WebhookOpener(Protocol):
    """Pinned opener behavior used by send-only webhook adapters."""

    def open(
        self,
        fullurl: str | Request,
        data: bytes | None = None,
        timeout: float | None = None,
    ) -> AbstractContextManager[WebhookResponse]: ...


def open_webhook(
    opener: WebhookOpener,
    request: Request,
    timeout: float,
) -> AbstractContextManager[WebhookResponse]:
    """Open a pinned webhook request with its typed response contract."""
    return opener.open(request, timeout=timeout)


class DeliveryTarget(Protocol):
    """Outbound adapter behavior returned by a registry factory."""

    def allowed(self, channel_id: str) -> bool: ...

    def health(self) -> str: ...

    def send(self, channel_id: str, text: str) -> bool: ...


@dataclass(frozen=True)
class ChannelEntry:
    """Contract for one named outbound channel adapter."""

    name: str
    factory: Callable[[Config], DeliveryTarget]
    validate_cfg: Callable[[Config], list[str]]
    health: Callable[[], str]
    max_message_len: int
    allowed: Callable[[str], bool]
    direction: str = "send-only"
