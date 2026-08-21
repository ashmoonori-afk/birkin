"""Immutable contracts and deterministic resolution for tool effects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal, Protocol, final

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


class ToolEffect(str, Enum):
    INSPECT = "inspect"
    CHANGE = "change"


@dataclass(frozen=True, slots=True)
class ToolOrigin:
    kind: Literal["native", "plugin"]
    plugin: str = ""
    version: str = ""
    bundle_digest: str = ""

    def __post_init__(self) -> None:
        if self.kind == "native":
            if self.plugin or self.version or self.bundle_digest:
                raise ValueError("native origins cannot contain plugin metadata")
        elif self.kind == "plugin":
            if not self.plugin or not self.version or not _DIGEST.fullmatch(self.bundle_digest):
                raise ValueError("plugin origins require plugin, version, and lowercase sha256 digest")
        else:
            raise ValueError("origin kind must be native or plugin")


@dataclass(frozen=True, slots=True)
class PluginToolId:
    plugin: str
    version: str
    bundle_digest: str
    tool: str

    def __post_init__(self) -> None:
        if not self.plugin or not self.version or not self.tool:
            raise ValueError("plugin tool identity fields cannot be empty")
        if not _DIGEST.fullmatch(self.bundle_digest):
            raise ValueError("bundle digest must be a 64-character lowercase sha256")


@dataclass(frozen=True, slots=True)
class InspectGrant:
    identity: PluginToolId
    parallel_safe: bool
    reason: str
    recorded_at: str

    def __post_init__(self) -> None:
        if type(self.parallel_safe) is not bool:
            raise ValueError("parallel_safe must be a boolean")
        if not 1 <= len(self.reason) <= 500 or any(ord(char) < 32 or ord(char) == 127 for char in self.reason):
            raise ValueError("reason must be 1-500 characters without control characters")
        if not _TIMESTAMP.fullmatch(self.recorded_at):
            raise ValueError("recorded_at must be UTC with second precision")
        try:
            datetime.strptime(self.recorded_at, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as exc:
            raise ValueError("recorded_at is not a valid timestamp") from exc


@dataclass(frozen=True, slots=True)
class EffectDecision:
    effect: ToolEffect
    parallel_safe: bool
    basis: Literal["native", "grant", "default", "invalid-file"]

    def __post_init__(self) -> None:
        if type(self.parallel_safe) is not bool:
            raise ValueError("parallel_safe must be a boolean")
        if self.effect is ToolEffect.CHANGE and self.parallel_safe:
            raise ValueError("change tools cannot be parallel-safe")


@dataclass(frozen=True, slots=True)
class EffectSnapshot:
    state: Literal["missing", "valid", "invalid"]
    grants: tuple[InspectGrant, ...]
    diagnostic: str = ""

    def __post_init__(self) -> None:
        if self.state not in ("missing", "valid", "invalid"):
            raise ValueError("invalid snapshot state")
        if self.state == "invalid" and self.grants:
            raise ValueError("invalid snapshots cannot expose grants")


@dataclass(frozen=True, slots=True)
class InventoryRow:
    identity: PluginToolId
    decision: EffectDecision
    state: Literal["active", "stale", "conflict"]
    detail: str = ""


class EffectLookup(Protocol):
    def decision_for(self, origin: ToolOrigin, tool_name: str) -> EffectDecision: ...


NATIVE_TOOL_ORIGIN = ToolOrigin("native")
NATIVE_INSPECT_PARALLEL_TOOLS = frozenset({
    "read_file", "list_files", "web_fetch", "session_search", "session_get",
    "memory_search", "memory_get_note", "memory_related",
})


@final
@dataclass(frozen=True, slots=True)
class SnapshotEffectLookup:
    snapshot: EffectSnapshot

    def decision_for(self, origin: ToolOrigin, tool_name: str) -> EffectDecision:
        if origin.kind == "native":
            inspect = tool_name in NATIVE_INSPECT_PARALLEL_TOOLS
            return EffectDecision(
                ToolEffect.INSPECT if inspect else ToolEffect.CHANGE, inspect, "native")
        if self.snapshot.state == "invalid":
            return EffectDecision(ToolEffect.CHANGE, False, "invalid-file")
        identity = PluginToolId(
            origin.plugin, origin.version, origin.bundle_digest, tool_name)
        for grant in self.snapshot.grants:
            if grant.identity == identity:
                return EffectDecision(ToolEffect.INSPECT, grant.parallel_safe, "grant")
        return EffectDecision(ToolEffect.CHANGE, False, "default")
