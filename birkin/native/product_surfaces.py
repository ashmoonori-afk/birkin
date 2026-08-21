"""Revision and delivery for Python-owned native product surfaces."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import final

from birkin.native.product_surface_authorities import (
    BrowserAsideProjectionSource as BrowserAsideProjectionSource,
)
from birkin.native.product_surface_authorities import (
    BrowserSurfaceAuthority as BrowserSurfaceAuthority,
)
from birkin.native.product_surface_authorities import (
    ComputerUseSurfaceAuthority as ComputerUseSurfaceAuthority,
)
from birkin.native.product_surface_authorities import (
    OfficeSurfaceAuthority as OfficeSurfaceAuthority,
)
from birkin.native.projection import public_native_mapping

SurfaceEventSink = Callable[[str, dict[str, object]], object]
SurfaceHandler = Callable[[dict[str, object]], dict[str, object]]

SURFACE_EVENT_SOURCES: Mapping[str, str] = {
    "browser.updated": "browser_aside",
    "office.updated": "office",
    "computer.updated": "computer_use",
}


@dataclass(frozen=True, slots=True)
class SurfaceSnapshot:
    surface: str
    revision: int
    payload: dict[str, object]
    full_snapshot: bool
    reset_reason: str


@final
class NativeProductSurfaceAuthority:
    """Revision and redact all product projections at the native boundary."""

    def __init__(
        self,
        *,
        browser: BrowserSurfaceAuthority,
        computer_use: ComputerUseSurfaceAuthority,
        office: OfficeSurfaceAuthority,
    ) -> None:
        self.browser = browser
        self.computer_use = computer_use
        self.office = office
        self._revisions = {name: 0 for name in self.surface_names}
        self._canonical: dict[str, str] = {}

    @property
    def surface_names(self) -> tuple[str, ...]:
        return ("browser_aside", "computer_use", "office")

    def _payload(self, surface: str) -> dict[str, object]:
        raw = {
            "browser_aside": self.browser.snapshot,
            "computer_use": self.computer_use.snapshot,
            "office": self.office.snapshot,
        }[surface]()
        public = public_native_mapping(raw)
        canonical = json.dumps(public, sort_keys=True, separators=(",", ":"))
        if self._canonical.get(surface) != canonical:
            self._canonical[surface] = canonical
            self._revisions[surface] += 1
        return public

    def live_snapshot(self, surface: str) -> SurfaceSnapshot | None:
        """Project one surface for live delivery, or nothing when unchanged.

        The shell advances a surface only on the exact next revision, so an
        event that leaves the canonical payload identical must publish no
        frame at all. Re-sending the current revision would read as a gap and
        force the shell to drop the surface and resubscribe.
        """
        if surface not in self._revisions:
            raise ValueError(f"unsupported native surface: {surface}")
        published = self._revisions[surface]
        payload = self._payload(surface)
        revision = self._revisions[surface]
        if revision == published:
            return None
        return SurfaceSnapshot(
            surface=surface,
            revision=revision,
            payload=payload,
            full_snapshot=False,
            reset_reason="live",
        )

    def snapshots(self, requested: Mapping[str, int]) -> tuple[SurfaceSnapshot, ...]:
        unknown = set(requested) - set(self.surface_names)
        if unknown:
            raise ValueError(f"unsupported native surfaces: {sorted(unknown)}")
        snapshots: list[SurfaceSnapshot] = []
        for surface in self.surface_names:
            if surface not in requested:
                continue
            known = requested[surface]
            if isinstance(known, bool) or known < 0:
                raise ValueError("surface revisions must be non-negative integers")
            payload = self._payload(surface)
            revision = self._revisions[surface]
            if known == revision:
                continue
            snapshots.append(SurfaceSnapshot(
                surface=surface,
                revision=revision,
                payload=payload,
                full_snapshot=True,
                reset_reason="initial" if known == 0 and revision == 1 else "revision_gap",
            ))
        return tuple(snapshots)

    def handlers(self, emit: SurfaceEventSink) -> dict[str, SurfaceHandler]:
        def wrapped(
            surface: str,
            event_type: str,
            operation: SurfaceHandler,
        ) -> SurfaceHandler:
            def handle(payload: dict[str, object]) -> dict[str, object]:
                result = operation(payload)
                _ = emit(event_type, {"surface": surface, "result": result})
                return result
            return handle

        return {
            "browser.start": wrapped("browser_aside", "browser.updated", self.browser.start),
            "browser.navigate": wrapped("browser_aside", "browser.updated", self.browser.navigate),
            "office.create": wrapped("office", "office.updated", self.office.create),
            "office.open": wrapped("office", "office.updated", self.office.open),
        }
