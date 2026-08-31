"""Telegram channel whose approved workflow results get a final editor pass."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import final
from typing_extensions import override

from ..polish import PolishConfig, polish_telegram_reply
from .base import TurnGateway
from .telegram import TelegramChannel


ProgressCallback = Callable[[dict[str, object]], None] | None


@final
class _PolishingGateway:
    _gateway: TurnGateway
    _polish_cfg: PolishConfig

    def __init__(
        self,
        gateway: TurnGateway,
        cfg: PolishConfig,
    ) -> None:
        self._gateway = gateway
        self._polish_cfg = cfg

    @property
    def pending_hard_restart(self) -> bool:
        return self._gateway.pending_hard_restart

    def do_hard_restart(self) -> None:
        self._gateway.do_hard_restart()

    def handle(
        self,
        channel: str,
        chat_id: str,
        text: str,
        on_text: Callable[[str], None] | None = None,
        workflow_id: str | None = None,
        on_progress: ProgressCallback = None,
        sender_id: str | None = None,
    ) -> str:
        # on_progress MUST be declared here: telegram._run_turn inspects
        # handle()'s signature and silently drops the callback when the
        # parameter is missing — which left approved-work turns (the long
        # ones) with a bare minute-counter heartbeat while the work stage
        # appeared only in the server log. Forwarding is capability-aware
        # (same guard as ask_session): older gateways / test doubles with the
        # narrower handle() must not TypeError.
        try:
            params = inspect.signature(self._gateway.handle).parameters
            accepts_kwargs = any(
                param.kind is inspect.Parameter.VAR_KEYWORD for param in params.values()
            )
            accepts_progress = "on_progress" in params or accepts_kwargs
            accepts_sender = "sender_id" in params or accepts_kwargs
        except (TypeError, ValueError):
            accepts_progress = False
            accepts_sender = False
        if accepts_progress and accepts_sender:
            reply = self._gateway.handle(
                channel,
                chat_id,
                text,
                on_text,
                workflow_id,
                on_progress,
                sender_id,
            )
        elif accepts_progress:
            reply = self._gateway.handle(
                channel,
                chat_id,
                text,
                on_text,
                workflow_id,
                on_progress,
            )
        elif accepts_sender:
            reply = self._gateway.handle(
                channel,
                chat_id,
                text,
                on_text,
                workflow_id,
                sender_id=sender_id,
            )
        else:
            reply = self._gateway.handle(
                channel,
                chat_id,
                text,
                on_text,
                workflow_id,
            )
        return polish_telegram_reply(reply, self._polish_cfg)


class PolishedTelegramChannel(TelegramChannel):
    _polish_cfg: PolishConfig

    def __init__(
        self,
        token: str,
        cfg: PolishConfig,
        allowed_chat_ids: list[str] | None = None,
        stream: bool = True,
        max_public_workers: int = 4,
    ) -> None:
        super().__init__(
            token,
            allowed_chat_ids=allowed_chat_ids,
            stream=stream,
            max_public_workers=max_public_workers,
        )
        self._polish_cfg = cfg

    @override
    def _run_turn(
        self,
        gateway: TurnGateway,
        chat_id: str,
        text: str,
        offset: int,
        workflow_id: str | None = None,
    ) -> None:
        if workflow_id is None:
            super()._run_turn(gateway, chat_id, text, offset)
            return
        super()._run_turn(
            _PolishingGateway(gateway, self._polish_cfg),
            chat_id,
            text,
            offset,
            workflow_id,
        )
