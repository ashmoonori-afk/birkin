"""Channel interface. A channel connects some transport (HTTP, Telegram, …) to
the gateway by calling ``gateway.handle(channel_name, chat_id, text)`` and
delivering the returned reply back to the user."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core import Gateway


class Channel:
    name: str = "base"

    def start(self, gateway: "Gateway") -> None:
        """Run the channel (blocking; called in its own thread)."""
        raise NotImplementedError
