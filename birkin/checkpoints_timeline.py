"""Durable tool timeline, task snapshots, and alternate-attempt lineage."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TimelineError(RuntimeError):
    """Checkpoint timeline metadata could not be persisted or decoded."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def workspace_key(workspace: Path) -> str:
    return hashlib.sha256(str(workspace.resolve()).encode("utf-8")).hexdigest()[:16]


class TimelineStore:
    """Small JSON/JSONL sidecar beside the shadow-git checkpoint store."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _dir(self, workspace: Path) -> Path:
        return self.root / workspace_key(workspace)

    @staticmethod
    def _write(path: Path, value: object) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
        except OSError as exc:
            raise TimelineError(str(exc)) from exc

    @staticmethod
    def _read(path: Path, fallback: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return fallback
        except (OSError, json.JSONDecodeError) as exc:
            raise TimelineError(str(exc)) from exc

    def append(self, workspace: Path, stream: str, value: dict[str, Any]) -> None:
        path = self._dir(workspace) / f"{stream}.jsonl"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        except OSError as exc:
            raise TimelineError(str(exc)) from exc

    def entries(self, workspace: Path, stream: str) -> list[dict[str, Any]]:
        path = self._dir(workspace) / f"{stream}.jsonl"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise TimelineError(str(exc)) from exc
        entries: list[dict[str, Any]] = []
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TimelineError(f"invalid {stream} record: {exc}") from exc
            if isinstance(value, dict):
                entries.append(value)
        return entries

    def snapshot_task(
        self,
        workspace: Path,
        checkpoint: str,
        value: dict[str, Any],
    ) -> None:
        self._write(
            self._dir(workspace) / "tasks" / f"{checkpoint}.json",
            value,
        )

    def task_changed(
        self,
        workspace: Path,
        checkpoint: str,
        current: dict[str, Any],
    ) -> bool:
        previous = self._read(
            self._dir(workspace) / "tasks" / f"{checkpoint}.json", None)
        return previous != current

    def copy_task_snapshots(
        self,
        workspace: Path,
        rewritten: dict[str, str],
    ) -> None:
        directory = self._dir(workspace) / "tasks"
        for previous, current in rewritten.items():
            value = self._read(directory / f"{previous}.json", None)
            if isinstance(value, dict):
                self._write(directory / f"{current}.json", value)

    def remove_task_snapshots(
        self,
        workspace: Path,
        checkpoints: set[str],
    ) -> None:
        directory = self._dir(workspace) / "tasks"
        for checkpoint in checkpoints:
            try:
                (directory / f"{checkpoint}.json").unlink(missing_ok=True)
            except OSError as exc:
                raise TimelineError(str(exc)) from exc

    def restore_task(
        self,
        workspace: Path,
        checkpoint: str,
    ) -> dict[str, Any]:
        path = self._dir(workspace) / "tasks" / f"{checkpoint}.json"
        value = self._read(path, None)
        if not isinstance(value, dict):
            raise TimelineError("checkpoint has no task/conversation snapshot")
        return value
