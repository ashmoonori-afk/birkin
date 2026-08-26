"""Compatibility imports for the canonical terminal authority."""

from __future__ import annotations

import sys

from ._darwin_pty import PtySupport
from .terminal_authority import TerminalAuthority
from .terminal_policy import allowed_signals
from .terminal_session import TerminalEventSink

__all__ = [
    "TerminalAuthority",
    "TerminalEventSink",
    "allowed_signals",
    "load_pty_support",
]

# Retained for existing platform-simulation characterizations.
_DARWIN = sys.platform == "darwin"
_WINDOWS = sys.platform == "win32"


def load_pty_support() -> PtySupport:
    """Load Darwin PTY support lazily for import compatibility."""
    from .darwin_terminal_process import load_pty_support as load

    return load()
