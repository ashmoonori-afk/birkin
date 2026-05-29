"""MCP (Model Context Protocol) server management — company tool connections.

birkin's gateway runs on Claude Code (a warm persistent process; see
``claude_session.py``), so it **inherits Claude Code's MCP servers natively** —
whatever MCP connections Claude Code has (Notion, Google Drive/Gmail/Calendar,
internal HTTP/stdio servers, …) are available to the agent with no extra wiring.

This module is the thin, friendly surface birkin puts on top of that: a
pass-through to ``claude mcp`` (so ``birkin mcp add|remove|list|get`` work with
the full Claude Code feature set) plus a tolerant parser of ``claude mcp list``
for birkin's own ``/mcp`` command and dashboard.

Pure standard library — shells out to the ``claude`` CLI via ``proc.cli_argv``.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional

from .proc import cli_argv


@dataclass(frozen=True)
class McpServer:
    name: str
    detail: str          # endpoint URL or launch command
    status: str          # raw status text, e.g. "✓ Connected", "needs-auth"
    connected: bool


def run(args: list[str], *, capture: bool = False,
        timeout: int = 60) -> subprocess.CompletedProcess:
    """Run ``claude mcp <args>``. By default inherits stdio (user sees output).

    With ``capture=True`` the output is captured (used by :func:`list_servers`).
    """
    argv = cli_argv(["claude", "mcp", *args])
    if capture:
        return subprocess.run(argv, capture_output=True, text=True,
                              errors="replace", timeout=timeout)
    return subprocess.run(argv, timeout=timeout)


def _parse_list(output: str) -> list[McpServer]:
    """Parse ``claude mcp list`` human output into structured rows.

    Each server line looks like ``<name>: <endpoint> - <status>`` where the
    name itself may contain colons (e.g. ``plugin:playwright:playwright``). We
    split the status off the right (last `` - ``) and the name off the left
    (last ``: `` before the endpoint), which handles both forms.
    """
    servers: list[McpServer] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or " - " not in line or ": " not in line:
            continue  # skip the "Checking MCP server health…" header etc.
        left, status = line.rsplit(" - ", 1)
        name, _, detail = left.rpartition(": ")
        name = name.strip()
        if not name:
            continue
        low = status.lower()
        connected = ("✓" in status) or ("connected" in low and "not" not in low)
        servers.append(McpServer(name=name, detail=detail.strip(),
                                 status=status.strip(), connected=connected))
    return servers


def list_servers(*, timeout: int = 60) -> tuple[list[McpServer], Optional[str]]:
    """Return (servers, error). ``error`` is non-None when ``claude mcp`` failed."""
    try:
        proc = run(["list"], capture=True, timeout=timeout)
    except FileNotFoundError:
        return [], "the `claude` CLI is not installed / not on PATH"
    except subprocess.TimeoutExpired:
        return [], "`claude mcp list` timed out"
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 and not out.strip():
        return [], f"`claude mcp list` failed (exit {proc.returncode})"
    return _parse_list(out), None
