"""Telegram channel whose approved workflow results get a final editor pass."""

from __future__ import annotations

import inspect
from collections.abc import Callable

from ..core import Gateway
from ..polish import PolishConfig, polish_telegram_reply
from .telegram import TelegramChannel


class _PolishingGateway(Gateway):
    def __init__(
        self,
        gateway: Gateway,
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
        on_progress: Callable[[dict], None] | None = None,
    ) -> str:
        # on_progress MUST be declared here: telegram._run_turn inspects
        # handle()'s signature and silently drops the callback when the
        # parameter is missing — which left approved-work turns (the long
        # ones) with a bare minute-counter heartbeat while the work stage
        # appeared only in the server log. Forwarding is capability-aware
        # (same guard as ask_session): older gateways / test doubles with the
        # narrower handle() must not TypeError.
        kwargs: dict[str, object] = {
            "on_text": on_text,
            "workflow_id": workflow_id,
        }
        if on_progress is not None:
            try:
                params = inspect.signature(self._gateway.handle).parameters
                accepts = ("on_progress" in params
                           or any(p.kind is inspect.Parameter.VAR_KEYWORD
                                  for p in params.values()))
            except (TypeError, ValueError):
                accepts = False
            if accepts:
                kwargs["on_progress"] = on_progress
        reply = self._gateway.handle(channel, chat_id, text, **kwargs)
        return polish_telegram_reply(reply, self._polish_cfg)


class PolishedTelegramChannel(TelegramChannel):
    def __init__(
        self,
        token: str,
        cfg: PolishConfig,
        allowed_chat_ids: list[str] | None = None,
        stream: bool = True,
    ) -> None:
        super().__init__(
            token,
            allowed_chat_ids=allowed_chat_ids,
            stream=stream,
        )
        self._polish_cfg = cfg

    def _run_turn(
        self,
        gateway: Gateway,
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
