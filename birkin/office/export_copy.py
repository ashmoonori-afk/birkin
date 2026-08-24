"""Durable temporary-copy primitive for Office export and rollback."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def copy_to_temporary(source: Path, directory: Path, suffix: str) -> Path:
    """Copy one file to a synced temporary peer and return its path."""
    descriptor, name = tempfile.mkstemp(
        prefix=".birkin-export-", suffix=suffix, dir=directory
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as outgoing, source.open("rb") as incoming:
            shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
            outgoing.flush()
            os.fsync(outgoing.fileno())
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    return temporary
