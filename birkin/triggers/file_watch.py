"""File watch trigger — fires when files matching patterns change."""

from __future__ import annotations

import asyncio
import logging
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable, Coroutine, Optional

from birkin.triggers.base import Trigger, TriggerConfig

logger = logging.getLogger(__name__)


class FileWatchTrigger(Trigger):
    """Watches a directory for file changes and fires the workflow.

    Config keys:
        path: Directory to watch (string).
        patterns: List of glob patterns to match (e.g. ["*.md", "*.txt"]).
        poll_interval: Seconds between polls (default: 5).
    """

    def __init__(self, trigger_config: TriggerConfig) -> None:
        super().__init__(trigger_config)
        self._watch_path = Path(trigger_config.config.get("path", "."))
        self._patterns: list[str] = trigger_config.config.get("patterns", ["*"])
        self._poll_interval: int = trigger_config.config.get("poll_interval", 5)
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._snapshot: dict[str, float] = {}

    async def start(self, on_fire: Callable[[TriggerConfig], Coroutine]) -> None:
        if self._running:
            return
        self._on_fire = on_fire
        self._running = True
        self._snapshot = self._take_snapshot()
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("FileWatchTrigger %s started: %s patterns=%s", self.id, self._watch_path, self._patterns)

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("FileWatchTrigger %s stopped", self.id)

    def is_running(self) -> bool:
        return self._running

    def _take_snapshot(self) -> dict[str, float]:
        """Record mtime of all matching files."""
        snap: dict[str, float] = {}
        if not self._watch_path.is_dir():
            return snap
        for f in self._watch_path.rglob("*"):
            if f.is_file() and any(fnmatch(f.name, p) for p in self._patterns):
                snap[str(f)] = f.stat().st_mtime
        return snap

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._poll_interval)
                new_snap = self._take_snapshot()
                changed = self._detect_changes(self._snapshot, new_snap)
                if changed and self._on_fire:
                    logger.info("FileWatchTrigger %s detected changes: %s", self.id, changed[:3])
                    await self._on_fire(self._config)
                self._snapshot = new_snap
            except asyncio.CancelledError:
                break
            except (OSError, RuntimeError) as exc:
                logger.error("FileWatchTrigger %s error: %s", self.id, exc)
                await asyncio.sleep(self._poll_interval * 2)

    @staticmethod
    def _detect_changes(old: dict[str, float], new: dict[str, float]) -> list[str]:
        """Return list of changed/added/removed file paths."""
        changes: list[str] = []
        for path, mtime in new.items():
            if path not in old or old[path] != mtime:
                changes.append(path)
        for path in old:
            if path not in new:
                changes.append(path)
        return changes
