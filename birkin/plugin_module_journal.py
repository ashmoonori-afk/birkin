"""Exact ``sys.modules`` ownership journaling for plugin transactions."""

from __future__ import annotations

import sys
from types import ModuleType


class _MissingModule:
    pass


_MISSING_MODULE = _MissingModule()


class ModuleJournal:
    """Restore prior objects only while transaction-owned objects remain."""

    def __init__(self) -> None:
        self._previous: dict[str, ModuleType | _MissingModule] = {}
        self._owned: dict[str, ModuleType] = {}

    def prepare(self, name: str) -> None:
        if name not in self._previous:
            self._previous[name] = (
                sys.modules[name]
                if name in sys.modules
                else _MISSING_MODULE
            )

    def own(self, name: str, module: ModuleType) -> None:
        self._owned[name] = module

    def rollback(self) -> None:
        for name, owned in reversed(tuple(self._owned.items())):
            if sys.modules.get(name) is not owned:
                continue
            previous = self._previous[name]
            if isinstance(previous, _MissingModule):
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
