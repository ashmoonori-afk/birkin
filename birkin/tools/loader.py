"""Plugin loader -- dynamic tool discovery.

TODO(BRA-59): Expand with:
- Directory-based plugin loading
- Entry-point-based discovery
- Validation of tool interface compliance
"""

from __future__ import annotations

from birkin.tools.base import Tool


def load_tools() -> list[Tool]:
    """Discover and instantiate all available tools.

    Returns an empty list until plugin discovery is implemented in BRA-59.
    """
    return []
