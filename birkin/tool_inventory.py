"""Deterministic installed-plugin inventory for tool effect attestations."""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Iterable, Set
from pathlib import Path

from .native_tool_metadata import NATIVE_TOOL_NAMES as _METADATA_NATIVE_TOOL_NAMES
from .tool_effects import (
    EffectSnapshot,
    InventoryRow,
    PluginToolId,
    SnapshotEffectLookup,
    ToolOrigin,
)
from .tools._types import Tool

# Include native names recovered outside the canonical metadata table so an
# attested plugin cannot replace either generation of Birkin-owned tools.
NATIVE_TOOL_NAMES = _METADATA_NATIVE_TOOL_NAMES | frozenset(
    {"office_rollback_request"}
)


def reconcile_inventory(
    tools: Iterable[Tool],
    snapshot: EffectSnapshot,
    *,
    native_names: Set[str] = NATIVE_TOOL_NAMES,
) -> tuple[InventoryRow, ...]:
    """Reconcile trusted installed tools with exact digest-bound grants."""
    candidates = tuple(tool for tool in tools if tool.origin.kind == "plugin")
    name_counts = Counter(tool.name for tool in candidates)
    lookup = SnapshotEffectLookup(snapshot)
    grants = {grant.identity: grant for grant in snapshot.grants}
    installed: set[PluginToolId] = set()
    rows: list[InventoryRow] = []

    for tool in candidates:
        origin = tool.origin
        identity = PluginToolId(
            origin.plugin, origin.version, origin.bundle_digest, tool.name
        )
        if identity in installed:
            continue
        installed.add(identity)
        if tool.name in native_names:
            state, detail = "conflict", "native tool with this name is active"
        elif name_counts[tool.name] > 1:
            state, detail = "conflict", "multiple plugins export this name"
        else:
            state = "active"
            decision = lookup.decision_for(origin, tool.name)
            if decision.basis == "grant":
                detail = grants[identity].reason
            elif decision.basis == "default":
                detail = "no-grant"
            else:
                detail = ""
        decision = lookup.decision_for(origin, tool.name)
        rows.append(InventoryRow(identity, decision, state, detail))

    for grant in snapshot.grants:
        if grant.identity not in installed:
            identity = grant.identity
            origin = ToolOrigin(
                "plugin", identity.plugin, identity.version, identity.bundle_digest
            )
            decision = lookup.decision_for(origin, identity.tool)
            rows.append(InventoryRow(identity, decision, "stale", grant.reason))

    return tuple(
        sorted(
            rows,
            key=lambda row: (
                row.identity.plugin,
                row.identity.tool,
                row.identity.version,
                row.identity.bundle_digest,
                row.state,
            ),
        )
    )


def load_inventory(
    snapshot: EffectSnapshot,
    project: Path | None = None,
) -> tuple[InventoryRow, ...]:
    """Load verified installed tools and return their reconciled inventory."""
    from .config import load_config
    from .plugin_install import plugin_trust_policy
    from .plugin_runtime import load_agent_tools, registry_roots

    project_root, team_root = registry_roots(project)
    plugin_keys, allow_unsigned = plugin_trust_policy(load_config())
    # SourceFileLoader normally writes __pycache__ into the signed bundle,
    # changing its digest after the first inventory read. Inventory is read-only.
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        tools = load_agent_tools(
            project_root,
            team_root,
            plugin_keys,
            allow_unsigned=allow_unsigned,
        )
    finally:
        sys.dont_write_bytecode = previous
    return reconcile_inventory(tools, snapshot)
