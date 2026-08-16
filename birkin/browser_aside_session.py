"""Browser session, tab, and action revision boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final


class BrowserSessionBoundaryError(RuntimeError):
    """A tab action token is stale or crosses a session boundary."""


@dataclass(frozen=True, slots=True)
class BrowserTab:
    tab_id: str
    generation: int
    url: str


@final
class BrowserSessionModel:
    def __init__(self, *, max_tabs: int) -> None:
        if max_tabs <= 0:
            raise ValueError("max_tabs must be positive")
        self._max_tabs = max_tabs
        self._tabs: dict[str, BrowserTab] = {}
        self._active: str | None = None
        self._generation = 0

    def open_tab(self, url: str) -> BrowserTab:
        if len(self._tabs) >= self._max_tabs:
            raise BrowserSessionBoundaryError("browser tab limit reached")
        self._generation += 1
        tab = BrowserTab(
            tab_id=f"tab-{self._generation}",
            generation=self._generation,
            url=url,
        )
        self._tabs[tab.tab_id] = tab
        self._active = tab.tab_id
        return tab

    def activate(self, tab_id: str) -> None:
        if tab_id not in self._tabs:
            raise BrowserSessionBoundaryError("browser tab is unknown")
        self._active = tab_id

    def action(
        self,
        tab_id: str,
        generation: int,
        kind: str,
    ) -> None:
        del kind
        tab = self._tabs.get(tab_id)
        if (
            tab is None
            or self._active != tab_id
            or tab.generation != generation
        ):
            raise BrowserSessionBoundaryError(
                "browser action token is stale"
            )


def browser_session_model(*, max_tabs: int) -> BrowserSessionModel:
    return BrowserSessionModel(max_tabs=max_tabs)
