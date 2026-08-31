"""Save oversized tool output to disk instead of throwing it away.

``run_shell`` cut results at 30K, ``web_fetch`` at 40K, ``read_file`` at 200KB
— and the remainder was simply gone. A build log whose error sat at line 900
of 2000 was unrecoverable; the agent's only move was to re-run the command and
hope for less output.

Now the full result is written to a file and the model gets a preview plus the
path, so it can grep the file or page through it with ``read_file offset=``.

``read_file`` is exempt on purpose: if reading a spill file could itself spill,
the agent would loop persist -> read -> persist forever. hermes pins the same
exemption for the same reason.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from .. import config, private_storage

SPILL_EXEMPT = frozenset({"read_file"})
PREVIEW_CHARS = 2_000
MARKER = "<persisted-output>"


def spill_dir(cfg: dict[str, Any]) -> Path:
    configured = (cfg.get("spill_dir") or "").strip()
    path = (
        Path(configured).expanduser()
        if configured
        else config.birkin_home() / "tool-results"
    )
    private_storage.harden_private_directory(path)
    return path


def _preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    """Cut at the last newline inside the budget so the preview ends cleanly."""
    if len(text) <= limit:
        return text
    window = text[:limit]
    cut = window.rfind("\n")
    return window[:cut] if cut > limit // 2 else window


def _sweep(directory: Path, retention_days: int) -> None:
    """Best-effort delete of spill files older than the retention window."""
    if retention_days <= 0:
        return
    cutoff = time.time() - retention_days * 86400
    try:
        entries = list(directory.glob("*.txt"))
    except OSError:
        return
    for entry in entries:
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            # A raced or already-deleted stale spill must not block this result.
            continue


def maybe_spill(content: str, tool_name: str, cfg: dict[str, Any]) -> str:
    """Return ``content``, or a preview+path block when it is too large.

    Never raises and never mutates: on any write failure it falls back to the
    old inline truncation, so a full disk degrades output rather than breaking
    the tool.
    """
    threshold = int(cfg.get("spill_threshold", 30_000) or 0)
    if (
        tool_name in SPILL_EXEMPT
        or threshold <= 0
        or not isinstance(content, str)
        or len(content) <= threshold
    ):
        return content

    try:
        directory = spill_dir(cfg)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        # Self-generated name: the registry never sees the tool_use_id, and
        # threading it through just to name a file is not worth the churn.
        path = directory / f"{stamp}_{tool_name}_{uuid.uuid4().hex[:8]}.txt"
        private_storage.atomic_write_private_text(path, content)
        _sweep(directory, int(cfg.get("spill_retention_days", 7) or 0))
    except OSError:
        return content[:threshold] + "\n[output truncated]"

    return (
        f"{MARKER}\n"
        f"This result was too large to inline ({len(content)} chars). "
        f"The full output is saved at:\n{path}\n"
        f"Page through it with read_file(path, offset=N) — each read tells "
        f"you the next offset. A shell search also works, but check its "
        f"exit status: a shell that mishandles the path can report zero "
        f"matches rather than an error.\n\n"
        f"Preview (first {PREVIEW_CHARS} chars):\n"
        f"{_preview(content)}\n"
        f"</persisted-output>"
    )
