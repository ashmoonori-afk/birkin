"""Cron trigger — fires workflows on a schedule using asyncio."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Coroutine, Optional

from birkin.triggers.base import Trigger, TriggerConfig

logger = logging.getLogger(__name__)


def _match_cron_field(field_expr: str, value: int, max_val: int) -> bool:
    """Check if a value matches a single cron field expression.

    Supports: * (any), exact number, */N (step), N-M (range), comma-separated.
    """
    for part in field_expr.split(","):
        part = part.strip()
        if part == "*":
            return True
        if "/" in part:
            base, step_str = part.split("/", 1)
            step = int(step_str)
            if base == "*":
                if value % step == 0:
                    return True
            else:
                start = int(base)
                if value >= start and (value - start) % step == 0:
                    return True
        elif "-" in part:
            lo, hi = part.split("-", 1)
            if int(lo) <= value <= int(hi):
                return True
        else:
            if int(part) == value:
                return True
    return False


def cron_matches(expression: str, dt_val: datetime) -> bool:
    """Check if a datetime matches a cron expression.

    Format: "minute hour day_of_month month day_of_week"
    Example: "0 9 * * 1" = every Monday at 9:00
    """
    parts = expression.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression (expected 5 fields): {expression!r}")

    minute, hour, dom, month, dow = parts
    return (
        _match_cron_field(minute, dt_val.minute, 59)
        and _match_cron_field(hour, dt_val.hour, 23)
        and _match_cron_field(dom, dt_val.day, 31)
        and _match_cron_field(month, dt_val.month, 12)
        and _match_cron_field(dow, dt_val.weekday(), 6)  # 0=Monday
    )


class CronTrigger(Trigger):
    """Fires a workflow on a cron schedule.

    Config keys:
        expression: Cron expression (e.g. "0 9 * * 1" for every Monday 9AM)
        timezone: Timezone name (default: UTC)

    Usage::

        config = TriggerConfig(type="cron", workflow_id="w1", config={"expression": "*/5 * * * *"})
        trigger = CronTrigger(config)
        await trigger.start(on_fire_callback)
    """

    def __init__(self, trigger_config: TriggerConfig) -> None:
        super().__init__(trigger_config)
        self._expression = trigger_config.config.get("expression", "* * * * *")
        self._task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def expression(self) -> str:
        return self._expression

    async def start(self, on_fire: Callable[[TriggerConfig], Coroutine]) -> None:
        if self._running:
            return
        self._on_fire = on_fire
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("CronTrigger %s started: %s", self.id, self._expression)

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("CronTrigger %s stopped", self.id)

    def is_running(self) -> bool:
        return self._running

    async def _poll_loop(self) -> None:
        """Poll every 30 seconds, fire when cron expression matches."""
        last_fired_minute: Optional[int] = None
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                current_minute = now.hour * 60 + now.minute

                if current_minute != last_fired_minute and cron_matches(self._expression, now):
                    last_fired_minute = current_minute
                    logger.info("CronTrigger %s firing for workflow %s", self.id, self.workflow_id)
                    if self._on_fire:
                        await self._on_fire(self._config)

                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except (OSError, RuntimeError, ValueError) as exc:
                logger.error("CronTrigger %s error: %s", self.id, exc)
                await asyncio.sleep(60)
