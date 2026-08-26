"""Deterministic installed-plugin inventory for tool effect attestations."""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Iterable, Set
from pathlib import Path

from .tool_effects import (
    EffectSnapshot,
    InventoryRow,
    PluginToolId,
    SnapshotEffectLookup,
    ToolOrigin,
)
from .tools._types import Tool

# Canonical Birkin-authored names that participate in native-vs-plugin
# collision handling. Optional groups are included so enabling one cannot make
# an attested plugin silently replace it.
NATIVE_TOOL_NAMES = frozenset({
    "read_file", "edit_file", "write_file", "list_files", "run_shell",
    "web_fetch", "web_search", "market_quote", "verify_citations",
    "session_search", "session_get", "vision_analyze", "browser_navigate",
    "browser_click", "browser_fill", "browser_press", "browser_execute",
    "browser_screenshot", "browser_evidence", "browser_close",
    "submit_payload", "list_document_adapters", "inspect_document",
    "extract_document", "compare_documents", "render_artifact",
    "validate_artifact", "office_job_request", "worker_invoke",
    "spawn_subagent", "desktop_windows", "window_screenshot", "computer_use",
    "companion_propose", "load_skill", "create_skill", "improve_skill",
    "remember", "memory_write_note", "memory_search", "memory_get_note",
    "memory_link", "memory_related", "memory_rezone",
})


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
            origin.plugin, origin.version, origin.bundle_digest, tool.name)
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
                "plugin", identity.plugin, identity.version,
                identity.bundle_digest)
            decision = lookup.decision_for(origin, identity.tool)
            rows.append(InventoryRow(
                identity, decision, "stale", grant.reason))

    return tuple(sorted(rows, key=lambda row: (
        row.identity.plugin, row.identity.tool, row.identity.version,
        row.identity.bundle_digest, row.state,
    )))


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
