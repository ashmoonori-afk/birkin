"""Shared terminal/web workspace protocol.

Presentation surfaces consume these contracts instead of owning session,
ordering, idempotency, or actor semantics.
"""

from .contracts import (
    CommandIdConflict,
    ConfigMutationRejected,
    ProtocolError,
    StaleCursor,
    WorkspaceCommand,
)
from .hub import WorkspaceHub, WorkspaceSession
from .presets import SESSION_PRESETS, SessionPreset
from .records import (
    CommandReceipt,
    WorkspaceEvent,
    WorkspaceSnapshot,
)
from .service import WorkspaceService
from .terminal import render_terminal

__all__ = [
    "CommandIdConflict",
    "CommandReceipt",
    "ConfigMutationRejected",
    "ProtocolError",
    "SESSION_PRESETS",
    "SessionPreset",
    "StaleCursor",
    "WorkspaceCommand",
    "WorkspaceEvent",
    "WorkspaceHub",
    "WorkspaceService",
    "WorkspaceSession",
    "WorkspaceSnapshot",
    "render_terminal",
]
