"""Contracts and deterministic resolution for tool effects."""

from __future__ import annotations

import dataclasses

import pytest

from birkin.tool_effects import (
    EffectDecision,
    EffectSnapshot,
    InspectGrant,
    NATIVE_INSPECT_PARALLEL_TOOLS,
    NATIVE_TOOL_ORIGIN,
    PluginToolId,
    SnapshotEffectLookup,
    ToolEffect,
    ToolOrigin,
)

DIGEST = "a" * 64
IDENTITY = PluginToolId("plug", "1.0", DIGEST, "echo")
GRANT = InspectGrant(IDENTITY, True, "reviewed", "2026-08-21T12:00:00Z")


def test_contracts_are_frozen_and_native_declarations_are_exact() -> None:
    assert NATIVE_INSPECT_PARALLEL_TOOLS == frozenset({
        "read_file", "list_files", "web_fetch", "session_search",
        "session_get", "memory_search", "memory_get_note", "memory_related",
    })
    with pytest.raises(dataclasses.FrozenInstanceError):
        GRANT.reason = "changed"  # type: ignore[misc]


def test_origin_and_identity_invariants() -> None:
    assert NATIVE_TOOL_ORIGIN == ToolOrigin("native")
    with pytest.raises(ValueError):
        ToolOrigin("native", plugin="unexpected")
    with pytest.raises(ValueError):
        ToolOrigin("plugin", "plug", "1", "A" * 64)
    with pytest.raises(ValueError):
        ToolOrigin("plugin", "", "1", DIGEST)
    with pytest.raises(ValueError):
        PluginToolId("plug", "1", "short", "echo")


def test_grant_and_decision_invariants() -> None:
    for bad_reason in ("", "x" * 501, "line\nbreak", "bad\x00reason"):
        with pytest.raises(ValueError):
            InspectGrant(IDENTITY, False, bad_reason, "2026-08-21T12:00:00Z")
    for timestamp in (
        "2026-08-21T12:00:00", "2026-08-21T12:00:00+00:00",
        "2026-08-21T12:00:00.000Z", "2026-02-30T12:00:00Z",
    ):
        with pytest.raises(ValueError):
            InspectGrant(IDENTITY, False, "ok", timestamp)
    with pytest.raises(ValueError):
        EffectDecision(ToolEffect.CHANGE, True, "default")


def test_invalid_snapshot_cannot_expose_grants() -> None:
    with pytest.raises(ValueError):
        EffectSnapshot("invalid", (GRANT,), "bad")


def test_resolution_is_exact_conservative_and_deterministic() -> None:
    lookup = SnapshotEffectLookup(EffectSnapshot("valid", (GRANT,)))
    assert lookup.decision_for(NATIVE_TOOL_ORIGIN, "read_file") == EffectDecision(
        ToolEffect.INSPECT, True, "native")
    assert lookup.decision_for(NATIVE_TOOL_ORIGIN, "Read_File") == EffectDecision(
        ToolEffect.CHANGE, False, "native")
    origin = ToolOrigin("plugin", "plug", "1.0", DIGEST)
    assert lookup.decision_for(origin, "echo") == EffectDecision(
        ToolEffect.INSPECT, True, "grant")
    assert lookup.decision_for(origin, "Echo") == EffectDecision(
        ToolEffect.CHANGE, False, "default")
    changed = ToolOrigin("plugin", "plug", "1.0", "b" * 64)
    assert lookup.decision_for(changed, "echo").basis == "default"


def test_invalid_snapshot_defaults_every_plugin_to_change_serial() -> None:
    lookup = SnapshotEffectLookup(EffectSnapshot("invalid", (), "broken"))
    origin = ToolOrigin("plugin", "plug", "1.0", DIGEST)
    assert lookup.decision_for(origin, "echo") == EffectDecision(
        ToolEffect.CHANGE, False, "invalid-file")
    assert lookup.decision_for(NATIVE_TOOL_ORIGIN, "read_file").basis == "native"
