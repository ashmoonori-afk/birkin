"""Trace storage — JSONL-based persistence for observability traces."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from birkin.observability.trace import Trace

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path(os.environ.get("BIRKIN_TRACES_DIR", "traces"))


class TraceStorage:
    """Append-only JSONL trace storage.

    Each session gets its own JSONL file. Supports querying by session
    and listing all traces.

    Usage::

        storage = TraceStorage(Path("traces"))
        storage.append(trace)
        traces = storage.query(session_id="s1")
    """

    def __init__(self, traces_dir: Optional[Path] = None) -> None:
        self._dir = traces_dir or _DEFAULT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def append(self, trace: Trace) -> None:
        """Append a trace to the JSONL file for its session."""
        session_id = trace.session_id or "unknown"
        file_path = self._dir / f"{session_id}.jsonl"
        line = trace.model_dump_json() + "\n"
        with file_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def query(self, session_id: str) -> list[Trace]:
        """Load all traces for a given session."""
        file_path = self._dir / f"{session_id}.jsonl"
        if not file_path.is_file():
            return []
        traces: list[Trace] = []
        for line in file_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                traces.append(Trace.model_validate_json(line))
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("Skipping malformed trace line: %s", exc)
        return traces

    def list_sessions(self) -> list[str]:
        """Return session IDs that have trace data."""
        return [p.stem for p in sorted(self._dir.glob("*.jsonl"))]

    def get_latest(self, session_id: str, limit: int = 10) -> list[Trace]:
        """Return the most recent traces for a session."""
        traces = self.query(session_id)
        return traces[-limit:]
