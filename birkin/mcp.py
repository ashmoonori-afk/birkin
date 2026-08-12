"""Manage external Claude MCP servers without promising Birkin inheritance.

``birkin mcp`` remains a pass-through to ``claude mcp`` so users can inspect
and manage Claude Code's global connections. In the default enforced-egress
mode, however, Birkin starts Claude with a strict MCP config and allows only
Birkin's own MCP tools. External Claude MCP servers are not inherited.

The module also provides a tolerant parser of ``claude mcp list`` for Birkin's
``/mcp`` command and dashboard.

Pure standard library — shells out to the ``claude`` CLI via ``proc.cli_argv``.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .proc import cli_argv


def scope_note() -> str:
    """Describe how global Claude MCP configuration relates to Birkin."""
    return (
        "External Claude MCP servers are managed here. With "
        "egress.enforced=true, Birkin sessions allow only Birkin MCP tools "
        "and do not inherit these servers."
    )


@dataclass(frozen=True)
class McpServer:
    name: str
    detail: str          # endpoint URL or launch command
    status: str          # raw status text, e.g. "✓ Connected", "needs-auth"
    connected: bool


def run(args: list[str], *, capture: bool = False,
        timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Run ``claude mcp <args>``. By default inherits stdio (user sees output).

    With ``capture=True`` the output is captured (used by :func:`list_servers`).
    """
    argv = cli_argv(["claude", "mcp", *args])
    if capture:
        return subprocess.run(argv, capture_output=True, text=True,
                              errors="replace", timeout=timeout, check=False)
    return subprocess.run(
        argv,
        text=True,
        errors="replace",
        timeout=timeout,
        check=False,
    )


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


def list_servers(*, timeout: int = 60) -> tuple[list[McpServer], str | None]:
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
