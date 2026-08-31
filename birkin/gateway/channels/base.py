"""Channel interface. A channel connects some transport (HTTP, Telegram, …) to
the gateway by calling ``gateway.handle(channel_name, chat_id, text)`` and
delivering the returned reply back to the user."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


ProgressCallback = Callable[[dict[str, object]], None] | None


class TurnGateway(Protocol):
    """Gateway behavior required by one Telegram turn."""

    @property
    def pending_hard_restart(self) -> bool: ...

    def do_hard_restart(self) -> None: ...

    def handle(
        self,
        channel: str,
        chat_id: str,
        text: str,
        on_text: Callable[[str], None] | None = None,
        workflow_id: str | None = None,
        on_progress: ProgressCallback = None,
        sender_id: str | None = None,
    ) -> str: ...


class ChannelGateway(TurnGateway, Protocol):
    """Complete gateway behavior used by inbound channel adapters."""

    def interrupt(self, channel: str, chat_id: str) -> bool: ...

    def take_restart_greeting(self, channel: str) -> str | None: ...

    def command_menu(self) -> list[dict[str, str]]: ...

    def restart_greeting(self) -> str: ...

    def pending_actions(self) -> list[dict[str, object]]: ...

    def resolve_action(self, aid: str, approve: bool) -> str: ...

    def claim_action(self, aid: str) -> tuple[str, bool]: ...

    def execute_claimed_action(
        self,
        aid: str,
        on_progress: ProgressCallback = None,
    ) -> str: ...

    def restore_action_claim(self, aid: str) -> None: ...

    def _command_trusted(self, channel: str) -> bool: ...


class Channel:
    name: str = "base"

    def start(self, _gateway: ChannelGateway) -> None:
        """Run the channel (blocking; called in its own thread)."""
        raise NotImplementedError
