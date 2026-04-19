"""Tests for birkin.triggers — cron, file_watch, webhook, message, scheduler."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from birkin.triggers.base import TriggerConfig
from birkin.triggers.cron import CronTrigger, cron_matches
from birkin.triggers.file_watch import FileWatchTrigger
from birkin.triggers.message import MessageTrigger
from birkin.triggers.scheduler import TriggerScheduler
from birkin.triggers.webhook import WebhookTrigger

# ---------------------------------------------------------------------------
# Cron expression matching
# ---------------------------------------------------------------------------


class TestCronMatches:
    def test_every_minute(self) -> None:
        dt = datetime(2026, 4, 16, 10, 30, tzinfo=UTC)
        assert cron_matches("* * * * *", dt) is True

    def test_specific_minute_hour(self) -> None:
        dt = datetime(2026, 4, 16, 9, 0, tzinfo=UTC)
        assert cron_matches("0 9 * * *", dt) is True
        assert cron_matches("30 9 * * *", dt) is False

    def test_step(self) -> None:
        dt5 = datetime(2026, 4, 16, 10, 15, tzinfo=UTC)
        assert cron_matches("*/5 * * * *", dt5) is True
        dt7 = datetime(2026, 4, 16, 10, 7, tzinfo=UTC)
        assert cron_matches("*/5 * * * *", dt7) is False

    def test_range(self) -> None:
        dt = datetime(2026, 4, 16, 10, 0, tzinfo=UTC)
        assert cron_matches("0 9-17 * * *", dt) is True
        dt_early = datetime(2026, 4, 16, 5, 0, tzinfo=UTC)
        assert cron_matches("0 9-17 * * *", dt_early) is False

    def test_day_of_week(self) -> None:
        # 2026-04-20 is Monday (weekday=0)
        dt_mon = datetime(2026, 4, 20, 9, 0, tzinfo=UTC)
        assert cron_matches("0 9 * * 0", dt_mon) is True
        assert cron_matches("0 9 * * 1", dt_mon) is False

    def test_comma_list(self) -> None:
        dt = datetime(2026, 4, 16, 10, 0, tzinfo=UTC)
        assert cron_matches("0 10,14,18 * * *", dt) is True
        assert cron_matches("0 11,14,18 * * *", dt) is False

    def test_invalid_expression(self) -> None:
        with pytest.raises(ValueError, match="expected 5 fields"):
            cron_matches("* * *", datetime.now(UTC))


# ---------------------------------------------------------------------------
# CronTrigger
# ---------------------------------------------------------------------------


class TestCronTrigger:
    def test_construction(self) -> None:
        cfg = TriggerConfig(type="cron", workflow_id="w1", config={"expression": "*/5 * * * *"})
        trigger = CronTrigger(cfg)
        assert trigger.expression == "*/5 * * * *"
        assert trigger.workflow_id == "w1"
        assert not trigger.is_running()

    @pytest.mark.asyncio
    async def test_start_stop(self) -> None:
        cfg = TriggerConfig(type="cron", workflow_id="w1", config={"expression": "* * * * *"})
        trigger = CronTrigger(cfg)
        callback = AsyncMock()

        await trigger.start(callback)
        assert trigger.is_running()

        await trigger.stop()
        assert not trigger.is_running()


# ---------------------------------------------------------------------------
# FileWatchTrigger
# ---------------------------------------------------------------------------


class TestFileWatchTrigger:
    def test_detect_changes(self) -> None:
        old = {"/a.txt": 1.0, "/b.txt": 2.0}
        new = {"/a.txt": 1.0, "/b.txt": 3.0, "/c.txt": 4.0}
        changes = FileWatchTrigger._detect_changes(old, new)
        assert "/b.txt" in changes  # modified
        assert "/c.txt" in changes  # added

    def test_detect_deletion(self) -> None:
        old = {"/a.txt": 1.0, "/b.txt": 2.0}
        new = {"/a.txt": 1.0}
        changes = FileWatchTrigger._detect_changes(old, new)
        assert "/b.txt" in changes

    @pytest.mark.asyncio
    async def test_start_stop(self, tmp_path: Path) -> None:
        cfg = TriggerConfig(
            type="file_watch",
            workflow_id="w1",
            config={"path": str(tmp_path), "patterns": ["*.md"]},
        )
        trigger = FileWatchTrigger(cfg)
        callback = AsyncMock()

        await trigger.start(callback)
        assert trigger.is_running()

        await trigger.stop()
        assert not trigger.is_running()


# ---------------------------------------------------------------------------
# WebhookTrigger
# ---------------------------------------------------------------------------


class TestWebhookTrigger:
    @pytest.mark.asyncio
    async def test_fire(self) -> None:
        cfg = TriggerConfig(type="webhook", workflow_id="w1", config={"path": "deploy"})
        trigger = WebhookTrigger(cfg)
        callback = AsyncMock()

        await trigger.start(callback)
        assert trigger.path == "deploy"

        fired = await trigger.fire()
        assert fired is True
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_fire_when_stopped(self) -> None:
        cfg = TriggerConfig(type="webhook", workflow_id="w1", config={})
        trigger = WebhookTrigger(cfg)
        fired = await trigger.fire()
        assert fired is False


# ---------------------------------------------------------------------------
# MessageTrigger
# ---------------------------------------------------------------------------


class TestMessageTrigger:
    def test_keyword_match(self) -> None:
        cfg = TriggerConfig(
            type="message",
            workflow_id="w1",
            config={"platform": "telegram", "keywords": ["deploy", "release"]},
        )
        trigger = MessageTrigger(cfg)
        trigger._running = True

        assert trigger.matches("please deploy now", "telegram") is True
        assert trigger.matches("hello world", "telegram") is False
        assert trigger.matches("please deploy now", "slack") is False

    def test_pattern_match(self) -> None:
        cfg = TriggerConfig(
            type="message",
            workflow_id="w1",
            config={"platform": "*", "patterns": [r"bug\s+#\d+"]},
        )
        trigger = MessageTrigger(cfg)
        trigger._running = True

        assert trigger.matches("Found bug #123", "telegram") is True
        assert trigger.matches("no bugs here", "slack") is False

    def test_wildcard_platform(self) -> None:
        cfg = TriggerConfig(
            type="message",
            workflow_id="w1",
            config={"platform": "*", "keywords": ["urgent"]},
        )
        trigger = MessageTrigger(cfg)
        trigger._running = True

        assert trigger.matches("urgent request", "telegram") is True
        assert trigger.matches("urgent request", "slack") is True

    @pytest.mark.asyncio
    async def test_check_and_fire(self) -> None:
        cfg = TriggerConfig(
            type="message",
            workflow_id="w1",
            config={"platform": "*", "keywords": ["help"]},
        )
        trigger = MessageTrigger(cfg)
        callback = AsyncMock()
        await trigger.start(callback)

        fired = await trigger.check_and_fire("I need help", "telegram")
        assert fired is True
        callback.assert_called_once()

        callback.reset_mock()
        fired = await trigger.check_and_fire("hello", "telegram")
        assert fired is False


# ---------------------------------------------------------------------------
# TriggerScheduler
# ---------------------------------------------------------------------------


class TestTriggerScheduler:
    @pytest.mark.asyncio
    async def test_add_and_remove(self) -> None:
        sched = TriggerScheduler()
        sched.register_type("webhook", WebhookTrigger)
        sched.set_default_callback(AsyncMock())

        cfg = TriggerConfig(type="webhook", workflow_id="w1", config={"path": "test"})
        trigger = await sched.add(cfg)
        assert len(sched) == 1
        assert trigger.is_running()

        removed = await sched.remove(cfg.id)
        assert removed is True
        assert len(sched) == 0

    @pytest.mark.asyncio
    async def test_duplicate_raises(self) -> None:
        sched = TriggerScheduler()
        sched.register_type("webhook", WebhookTrigger)
        sched.set_default_callback(AsyncMock())

        cfg = TriggerConfig(id="dup", type="webhook", workflow_id="w1")
        await sched.add(cfg)
        with pytest.raises(ValueError, match="already exists"):
            await sched.add(cfg)

    @pytest.mark.asyncio
    async def test_unknown_type_raises(self) -> None:
        sched = TriggerScheduler()
        sched.set_default_callback(AsyncMock())

        cfg = TriggerConfig(type="unknown", workflow_id="w1")
        with pytest.raises(ValueError, match="Unknown trigger type"):
            await sched.add(cfg)

    @pytest.mark.asyncio
    async def test_shutdown(self) -> None:
        sched = TriggerScheduler()
        sched.register_type("webhook", WebhookTrigger)
        sched.set_default_callback(AsyncMock())

        for i in range(3):
            cfg = TriggerConfig(type="webhook", workflow_id=f"w{i}")
            await sched.add(cfg)

        assert len(sched) == 3
        await sched.shutdown()
        assert len(sched) == 0

    @pytest.mark.asyncio
    async def test_list_configs(self) -> None:
        sched = TriggerScheduler()
        sched.register_type("webhook", WebhookTrigger)
        sched.set_default_callback(AsyncMock())

        cfg = TriggerConfig(type="webhook", workflow_id="w1")
        await sched.add(cfg)

        configs = sched.list_configs()
        assert len(configs) == 1
        assert configs[0].workflow_id == "w1"
