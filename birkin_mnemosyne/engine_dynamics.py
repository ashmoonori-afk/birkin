"""Note reinforcement and zone-priority operations for the memory engine."""

from __future__ import annotations

from datetime import date, datetime, timezone

from .dynamics import (
    decayed_ema,
    default_dynamics,
    effective_strength,
    potentiate,
)
from .index_store import IndexStore
from .index_types import NoteDynamics


class DynamicsEngine(IndexStore):
    """Persisted note dynamics and normalized zone priorities."""

    def dynamics_of(self, note_slug: str) -> NoteDynamics:
        with self._lock:
            if self._dyn is None:
                self._load()
            assert self._dyn is not None
            dynamics = self._dyn["notes"].get(note_slug)
            if dynamics:
                return dynamics.copy()
            entry = (self._notes or {}).get(note_slug)
            return default_dynamics(entry["created"] if entry else None)

    def set_dynamics(
        self,
        note_slug: str,
        dynamics: NoteDynamics,
    ) -> None:
        """Overwrite one note's dynamics for maintenance or tests."""
        with self._lock:
            if self._dyn is None:
                self._load()
            assert self._dyn is not None
            self._dyn["notes"][note_slug] = dynamics.copy()
            self._save_dynamics()

    def effective_of(
        self,
        note_slug: str,
        now: datetime | None = None,
    ) -> float:
        observed_at = now or datetime.now(timezone.utc)
        return effective_strength(self.dynamics_of(note_slug), observed_at)

    def record_access(
        self,
        note_slug: str,
        now: datetime | None = None,
    ) -> None:
        """Potentiate a known note and bump its zone priority."""
        observed_at = now or datetime.now(timezone.utc)
        with self._lock:
            if self._notes is None:
                self._load()
            assert self._notes is not None and self._dyn is not None
            entry = self._notes.get(note_slug)
            if entry is None:
                self.refresh()
                entry = self._notes.get(note_slug)
                if entry is None:
                    return
            self._dyn["notes"][note_slug] = potentiate(
                self.dynamics_of(note_slug),
                observed_at,
            )
            zone = entry["zone"]
            zone_state = self._dyn["zones"].get(zone)
            today = observed_at.date()
            ema = decayed_ema(
                zone_state["ema"] if zone_state else 0.0,
                zone_state["last_hit"] if zone_state else None,
                today,
            ) + 1.0
            self._dyn["zones"][zone] = {
                "ema": ema,
                "last_hit": today.isoformat(),
            }
            self._save_dynamics()

    def zone_priorities(self, today: date | None = None) -> dict[str, float]:
        """Return normalized priorities for zones currently in the vault."""
        observed_date = today or datetime.now(timezone.utc).date()
        with self._lock:
            if self._notes is None:
                self._load()
            assert self._notes is not None and self._dyn is not None
            zones = {entry["zone"] for entry in self._notes.values()}
            raw: dict[str, float] = {}
            for zone in zones:
                state = self._dyn["zones"].get(zone)
                raw[zone] = decayed_ema(
                    state["ema"] if state else 0.0,
                    state["last_hit"] if state else None,
                    observed_date,
                )
            maximum = max(raw.values(), default=0.0)
            return {
                zone: (value / maximum if maximum > 0 else 0.0)
                for zone, value in raw.items()
            }
