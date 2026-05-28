"""Backwards-compatibility shim — the routine was renamed to **Morpheus**.

This module re-exports everything from :mod:`birkin.morpheus` so any external
import path that still says ``birkin.nightly`` keeps working.
"""

from __future__ import annotations

from .morpheus import (   # noqa: F401  (re-exports for backwards compatibility)
    _MORPHEUS_TASK as _NIGHTLY_TASK,
    _attach_propose_tool,
    _gather_changed_files,
    _gather_sessions,
    run_once,
)
