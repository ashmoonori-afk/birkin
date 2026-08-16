"""Typing features whose stdlib availability follows the Python version."""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = ["NotRequired"]

if TYPE_CHECKING:
    from typing_extensions import NotRequired
else:
    try:
        from typing import NotRequired
    except ImportError:

        class NotRequired:
            """Runtime-only Python 3.10 shim for postponed annotations."""

            def __class_getitem__(cls, item: object) -> object:
                return item
