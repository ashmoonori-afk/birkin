"""Whether an edit left the file in a state a language server complains about.

Off unless ``lsp_servers`` maps the file's suffix to a command, and free when
off: no configured server means no import of the client, no subprocess, and a
tool result byte-identical to before. Most edits are to files no server covers,
and every one of them would otherwise pay a process spawn.

Only NEW problems are reported. A file that already had ten warnings must not
blame all ten on this edit -- the one the agent just caused is the one worth a
line in the tool result.

Nothing here can fail an edit. A missing binary, a wedged server, a malformed
config entry: all of them return "" and the edit stands. Diagnostics are a
courtesy on top of a write that already succeeded.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

MAX_REPORTED = 10
_SEVERITY = {1: "error", 2: "warning", 3: "info", 4: "hint"}


def server_for(path: Path, cfg: dict[str, Any]) -> Optional[list[str]]:
    """The command serving this file's suffix, or ``None``."""
    servers = (cfg or {}).get("lsp_servers") or {}
    if not isinstance(servers, dict):
        return None
    argv = servers.get(Path(path).suffix)
    if not isinstance(argv, (list, tuple)) or not argv:
        return None
    if not all(isinstance(part, str) for part in argv):
        return None
    return list(argv)


def _format(found: list[dict[str, Any]]) -> str:
    lines = []
    for item in found[:MAX_REPORTED]:
        start = ((item.get("range") or {}).get("start") or {})
        where = f"{int(start.get('line', 0)) + 1}:{int(start.get('character', 0)) + 1}"
        level = _SEVERITY.get(item.get("severity"), "note")
        code = item.get("code")
        label = f"[{code}] " if code else ""
        lines.append(f"  {where} {level}: {label}{item.get('message', '')}")
    if len(found) > MAX_REPORTED:
        lines.append(f"  … and {len(found) - MAX_REPORTED} more")
    return "\n<diagnostics>\n" + "\n".join(lines) + "\n</diagnostics>"


def report_for(path: Path, text: str, cfg: dict[str, Any],
               baseline_text: Optional[str] = None) -> str:
    """A block naming the problems this edit introduced, or ``""``.

    ``baseline_text`` is the file as it was; diagnostics it already produced are
    subtracted, so the report is what changed rather than what exists.
    """
    argv = server_for(path, cfg)
    if argv is None:
        return ""
    from .client import LspClient
    from .protocol import LspError, new_since
    try:
        with LspClient(argv, timeout=float((cfg or {}).get("lsp_timeout", 10.0))) as client:
            client.request("initialize", {"processId": None, "rootUri": None,
                                          "capabilities": {}})
            baseline: list[dict[str, Any]] = []
            if baseline_text is not None:
                baseline = client.diagnostics_for(path, baseline_text)
            current = client.diagnostics_for(path, text)
    except LspError:
        # A server that will not start or will not answer costs the edit
        # nothing: the write already succeeded.
        return ""
    fresh = new_since(baseline, current)
    return _format(fresh) if fresh else ""
