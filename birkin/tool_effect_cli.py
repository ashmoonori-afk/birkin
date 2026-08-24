"""Command-line management for plugin tool effect attestations."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from .tool_attestations import AttestationError, ToolAttestationStore
from .tool_effects import InspectGrant, InventoryRow, PluginToolId, ToolEffect
from .tool_inventory import load_inventory

def _parser(action: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"birkin plugins effects {action}")
    parser.add_argument("values", nargs="*")
    parser.add_argument("--json", action="store_true", help="machine-readable JSON")
    if action == "set":
        parser.add_argument("--reason")
        parser.add_argument("--parallel-safe", action="store_true")
    elif action == "reset":
        parser.add_argument("--yes", action="store_true")
    return parser

def _sentence(message: str) -> str:
    return message if message.endswith((".", "!", "?")) else message + "."

def _emit(payload: dict[str, Any], text: str, json_mode: bool) -> None:
    print(json.dumps(payload, sort_keys=True) if json_mode else text)

def _semantic(message: str, json_mode: bool) -> int:
    rendered = f"Tool effect error: {_sentence(message)}"
    _emit({"error": rendered}, rendered, json_mode)
    return 1

def _file_error(diagnostic: str, json_mode: bool) -> int:
    rendered = f"Tool effect file error: {_sentence(diagnostic)}"
    _emit({"error": rendered}, rendered, json_mode)
    return 1

def _row_record(row: InventoryRow) -> dict[str, Any]:
    identity = row.identity
    return {
        "basis": row.decision.basis,
        "bundle_digest": identity.bundle_digest,
        "detail": row.detail,
        "effect": row.decision.effect.value,
        "parallel_safe": row.decision.parallel_safe,
        "plugin": identity.plugin,
        "plugin_version": identity.version,
        "state": row.state,
        "tool": identity.tool,
    }

def _summary(rows: tuple[InventoryRow, ...]) -> dict[str, int]:
    active = tuple(row for row in rows if row.state == "active")
    return {
        "inspect": sum(row.decision.effect is ToolEffect.INSPECT for row in active),
        "change": sum(row.decision.effect is ToolEffect.CHANGE for row in active),
        "stale": sum(row.state == "stale" for row in rows),
    }

def _row_status(row: InventoryRow) -> str:
    if row.state == "stale":
        return f"stale:{row.detail}"
    if row.state == "conflict":
        return f"conflict:{row.detail}"
    if row.decision.basis == "grant":
        return f"grant:{row.detail}"
    if row.decision.basis == "default":
        return "default:no-grant"
    return row.decision.basis

def _render_rows(rows: tuple[InventoryRow, ...], summary: dict[str, int]) -> str:
    lines = []
    for row in rows:
        identity = row.identity
        schedule = "parallel" if row.decision.parallel_safe else "serial"
        lines.append(
            f"{identity.plugin}@{identity.version}/{identity.tool}  "
            f"{row.decision.effect.value}  {schedule}  {_row_status(row)}")
    lines.append(
        f"summary  inspect={summary['inspect']}  change={summary['change']}  "
        f"stale={summary['stale']}")
    return "\n".join(lines)

def _list(argv: Sequence[str]) -> int:
    args = _parser("list").parse_args(argv)
    if args.values:
        return _semantic("list takes no positional arguments", args.json)
    store = ToolAttestationStore()
    snapshot = store.load()
    rows = load_inventory(snapshot)
    summary = _summary(rows)
    payload: dict[str, Any] = {
        "rows": [_row_record(row) for row in rows], "summary": summary}
    prefix = ""
    if snapshot.state == "invalid":
        error = f"Tool effect file error: {_sentence(snapshot.diagnostic)}"
        payload["error"] = error
        prefix = error + "\n"
    _emit(payload, prefix + _render_rows(rows, summary), args.json)
    return 1 if snapshot.state == "invalid" else 0

def _target(rows: tuple[InventoryRow, ...], plugin: str, tool: str,
            json_mode: bool) -> PluginToolId | int:
    matches = tuple(
        row for row in rows
        if row.identity.plugin == plugin and row.identity.tool == tool)
    if any(row.state == "conflict" for row in matches):
        return _semantic(
            f"plugin tool '{plugin}/{tool}' is in a name collision", json_mode)
    for row in matches:
        if row.state == "active":
            return row.identity
    return _semantic(
        f"unknown or inactive plugin tool '{plugin}/{tool}'", json_mode)

def _set(argv: Sequence[str]) -> int:
    args = _parser("set").parse_args(argv)
    if len(args.values) != 3:
        return _semantic("set requires PLUGIN TOOL EFFECT", args.json)
    plugin, tool, effect = args.values
    if effect not in ("inspect", "change"):
        return _semantic("effect must be 'inspect' or 'change'", args.json)
    reason = args.reason if isinstance(args.reason, str) else ""
    if effect == "inspect" and not reason.strip():
        return _semantic("inspect requires a non-empty --reason", args.json)
    if effect == "change" and args.parallel_safe:
        return _semantic("--parallel-safe is only valid with inspect", args.json)
    if effect == "change" and reason:
        return _semantic("--reason is only valid with inspect", args.json)

    store = ToolAttestationStore()
    snapshot = store.load()
    if snapshot.state == "invalid":
        return _file_error(snapshot.diagnostic, args.json)
    identity = _target(load_inventory(snapshot), plugin, tool, args.json)
    if isinstance(identity, int):
        return identity
    grants = tuple(
        grant for grant in snapshot.grants if grant.identity != identity)
    parallel_safe = bool(args.parallel_safe) if effect == "inspect" else False
    if effect == "inspect":
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        grants += (InspectGrant(
            identity, parallel_safe, reason, stamp),)
    store.write(grants)
    payload = {
        "bundle_digest": identity.bundle_digest,
        "effect": effect,
        "parallel_safe": parallel_safe,
        "plugin": identity.plugin,
        "plugin_version": identity.version,
        "tool": identity.tool,
    }
    verb = "Recorded inspect grant" if effect == "inspect" else "Recorded change posture"
    text = (
        f"{verb} for {identity.plugin}@{identity.version}/{identity.tool}.\n"
        f"digest  {identity.bundle_digest}\n"
        f"schedule  {'parallel' if parallel_safe else 'serial'}")
    _emit(payload, text, args.json)
    return 0

def _prune(argv: Sequence[str]) -> int:
    args = _parser("prune").parse_args(argv)
    if args.values:
        return _semantic("prune takes no positional arguments", args.json)
    store = ToolAttestationStore()
    snapshot = store.load()
    if snapshot.state == "invalid":
        return _file_error(snapshot.diagnostic, args.json)
    stale = {
        row.identity for row in load_inventory(snapshot) if row.state == "stale"}
    remaining = tuple(
        grant for grant in snapshot.grants if grant.identity not in stale)
    if stale:
        store.write(remaining)
    count = len(snapshot.grants) - len(remaining)
    noun = "grant" if count == 1 else "grants"
    _emit({"pruned": count}, f"Pruned {count} stale tool effect {noun}.", args.json)
    return 0

def _reset(argv: Sequence[str]) -> int:
    args = _parser("reset").parse_args(argv)
    if args.values:
        return _semantic("reset takes no positional arguments", args.json)
    if not args.yes:
        return _semantic("reset requires --yes", args.json)
    backup = ToolAttestationStore().reset()
    payload = {"backup": backup.name if backup else None, "reset": True}
    text = "Reset tool effects."
    if backup is not None:
        text = f"Reset tool effects; previous bytes saved as {backup.name}."
    _emit(payload, text, args.json)
    return 0

_ACTIONS = {
    "list": _list, "prune": _prune, "reset": _reset, "set": _set,
}

def run(argv: Sequence[str]) -> int:
    """Dispatch one nested tool-effects action and return its exit code."""
    tokens = list(argv)
    action = "list"
    if tokens and not tokens[0].startswith("-"):
        action = tokens.pop(0)
    handler = _ACTIONS.get(action)
    if handler is None:
        message = (
            f"Unknown tool-effects action '{action}'; valid actions: "
            + ", ".join(sorted(_ACTIONS)))
        _emit({"error": message}, message, "--json" in tokens)
        return 1
    try:
        return handler(tokens)
    except AttestationError as exc:
        return _file_error(str(exc), "--json" in tokens)
    except (OSError, RuntimeError, ValueError) as exc:
        return _semantic(str(exc), "--json" in tokens)
