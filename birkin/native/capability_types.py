"""Value types for connection-scoped native session capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import final


@final
@dataclass(frozen=True, slots=True)
class CapabilityScope:
    instance_id: str
    connection_id: str
    surface: str
    view_id: str


@final
@dataclass(frozen=True, slots=True)
class SessionCapability:
    token: str
    expires_at: datetime
    hard_expires_at: datetime
    scope: CapabilityScope
