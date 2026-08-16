"""User-supplied shell scripts on birkin's lifecycle events.

birkin had no extension point other than skills and MCP: any policy of your own
— "never let the agent touch prod config", "log every tool call to our audit
system", "inject today's on-call rota before each turn" — meant forking.

A hook is a shell command run at one of three moments, given JSON on stdin and
answering with JSON on stdout:

``pre_tool_call``   can BLOCK the call; its message becomes the tool result.
``post_tool_call``  observation only; the return value is ignored.
``pre_llm_call``    may return ``{"context": "..."}`` to add to this turn.

The wire format matches Claude Code's, so an existing hook script works
unchanged, and both ``{"decision": "block", "reason": ...}`` and
``{"action": "block", "message": ...}`` are accepted.

**This is arbitrary code execution by design.** Each (event, command) pair is
confirmed once and remembered in an allowlist; unattended processes without an
explicit opt-in skip hooks entirely rather than running something nobody
approved.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from . import config, store
from .proc import ShellCommand, run_shell_command, shell_env

EVENTS = ("pre_tool_call", "post_tool_call", "pre_llm_call")

# Shorter than hermes' 60s: this sits on the tool path, where a wedged hook is
# felt on every call.
DEFAULT_TIMEOUT = 10
MAX_TIMEOUT = 300
MAX_CONTEXT_CHARS = 8_000
_EXECUTION_CONTRACT = "managed-shell-v1"


@dataclass(frozen=True)
class HookSpec:
    event: str
    command: str
    matcher: str = ""          # regex, fullmatch against the tool name
    timeout: int = DEFAULT_TIMEOUT

    def matches(self, tool_name: str) -> bool:
        if not self.matcher:
            return True
        try:
            return re.fullmatch(self.matcher, tool_name or "") is not None
        except re.error:
            return self.matcher == tool_name    # bad regex -> literal compare


def _allowlist_path() -> Path:
    return config.birkin_home() / "hooks_allowlist.json"


def parse_hooks(cfg: dict[str, Any]) -> list[HookSpec]:
    """Read ``cfg["hooks"]``. Malformed entries are skipped, never fatal."""
    raw = cfg.get("hooks") or {}
    if not isinstance(raw, dict):
        return []
    specs: list[HookSpec] = []
    for event, entries in raw.items():
        if event not in EVENTS:
            print(f"[birkin] unknown hook event {event!r} — expected one of "
                  f"{', '.join(EVENTS)}", flush=True)
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str):
                entry = {"command": entry}
            if not isinstance(entry, dict):
                continue
            command = str(entry.get("command", "")).strip()
            if not command:
                continue
            try:
                timeout = int(entry.get("timeout", DEFAULT_TIMEOUT))
            except (TypeError, ValueError):
                timeout = DEFAULT_TIMEOUT
            matcher = str(entry.get("matcher", "") or "")
            if matcher and event == "pre_llm_call":
                matcher = ""        # no tool name to match against
            specs.append(HookSpec(event=event, command=command, matcher=matcher,
                                  timeout=max(1, min(MAX_TIMEOUT, timeout))))
    return specs


# -- consent ---------------------------------------------------------------

def _load_allowlist() -> list[dict[str, str]]:
    data = store._read_json(_allowlist_path(), [])
    return data if isinstance(data, list) else []


def is_allowed(spec: HookSpec, entries: Optional[list[dict[str, str]]] = None
               ) -> bool:
    entries = _load_allowlist() if entries is None else entries
    return any(
        entry.get("event") == spec.event
        and entry.get("command") == spec.command
        and entry.get("execution_contract") == _EXECUTION_CONTRACT
        for entry in entries
    )


def allow(spec: HookSpec) -> None:
    """Record consent. Locked, because the gateway and REPL may both run."""
    path = _allowlist_path()
    try:
        with store.file_lock(path):
            entries = _load_allowlist()
            if not is_allowed(spec, entries):
                entries.append({
                    "event": spec.event,
                    "command": spec.command,
                    "execution_contract": _EXECUTION_CONTRACT,
                    "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                })
                store._write_json(path, entries)
    except store.FileLockTimeout:
        pass


def revoke(command: str) -> int:
    """Forget consent for every event of ``command``. Returns entries removed."""
    path = _allowlist_path()
    try:
        with store.file_lock(path):
            entries = _load_allowlist()
            keep = [e for e in entries if e.get("command") != command]
            removed = len(entries) - len(keep)
            if removed:
                store._write_json(path, keep)
            return removed
    except store.FileLockTimeout:
        return 0


def _consent(spec: HookSpec, cfg: dict[str, Any]) -> bool:
    """Decide whether ``spec`` may run, asking once if there is a terminal."""
    if is_allowed(spec):
        return True
    if os.environ.get("BIRKIN_ACCEPT_HOOKS") == "1" \
            or cfg.get("hooks_auto_accept"):
        allow(spec)
        return True
    try:
        interactive = sys.stdin.isatty()
    except Exception:
        interactive = False
    if not interactive:
        # Headless and not pre-approved: skip rather than silently execute.
        print(f"[birkin] hook not approved, skipping: {spec.event} -> "
              f"{spec.command} (approve it in a terminal, or set "
              f"hooks_auto_accept)", flush=True)
        return False
    print(f"\n[birkin] A hook wants to run on {spec.event}:\n"
          f"    {spec.command}\n"
          f"  This executes on your machine with your permissions, every time "
          f"the event fires.")
    try:
        answer = input("  Allow it from now on? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"
    if answer in ("y", "yes"):
        allow(spec)
        return True
    return False


# -- execution -------------------------------------------------------------

def run_hook(spec: HookSpec, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Run the hook and parse its stdout. None means "no opinion"."""
    try:
        proc = run_shell_command(
            ShellCommand(
                command=os.path.expanduser(spec.command),
                cwd=None,
                timeout=spec.timeout,
                environment=shell_env(),
                stdin=json.dumps(payload, ensure_ascii=False),
                hide_window=True,
            )
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[birkin] hook failed ({spec.command}): {exc}", flush=True)
        return None
    return _parse_response(proc.stdout)


def _parse_response(stdout: str) -> Optional[dict[str, Any]]:
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    # Claude Code's shape and the canonical one both mean "block".
    decision = str(obj.get("decision", "")).lower()
    action = str(obj.get("action", "")).lower()
    if decision == "block" or action == "block":
        return {"action": "block",
                "message": str(obj.get("reason") or obj.get("message")
                               or "blocked by a hook")}
    if obj.get("context"):
        return {"context": str(obj["context"])}
    return None


class HookBus:
    """Dispatches the configured hooks. Failures are non-fatal by design."""

    def __init__(self, specs: list[HookSpec], session_id: str = ""):
        self.specs = specs
        self.session_id = session_id

    def _for(self, event: str, tool_name: str = "") -> list[HookSpec]:
        return [s for s in self.specs
                if s.event == event and s.matches(tool_name)]

    def _payload(self, event: str, **extra: Any) -> dict[str, Any]:
        return {"hook_event_name": event, "session_id": self.session_id,
                "cwd": str(Path.cwd()), **extra}

    def pre_tool(self, tool_name: str,
                 tool_input: dict[str, Any]) -> Optional[str]:
        """Returns a block message, or None to let the call proceed."""
        for spec in self._for("pre_tool_call", tool_name):
            result = run_hook(spec, self._payload(
                "pre_tool_call", tool_name=tool_name, tool_input=tool_input))
            if result and result.get("action") == "block":
                return result["message"]        # first block wins
        return None

    def post_tool(self, tool_name: str, tool_input: dict[str, Any],
                  content: str, is_error: bool) -> None:
        for spec in self._for("post_tool_call", tool_name):
            run_hook(spec, self._payload(
                "post_tool_call", tool_name=tool_name, tool_input=tool_input,
                extra={"is_error": is_error, "content": content[:4000]}))

    def pre_llm(self, user_text: str, model: str = "",
                provider: str = "") -> str:
        parts: list[str] = []
        for spec in self._for("pre_llm_call"):
            result = run_hook(spec, self._payload(
                "pre_llm_call", extra={"user_text": user_text[:4000],
                                       "model": model, "provider": provider}))
            if result and result.get("context"):
                parts.append(result["context"])
        joined = "\n\n".join(parts)
        return joined[:MAX_CONTEXT_CHARS]


def build_bus(cfg: dict[str, Any], session_id: str = "") -> Optional[HookBus]:
    """Build the bus, or None when no hook is configured and approved.

    None is the zero-overhead path: with no hooks in config, nothing anywhere
    pays for this feature.
    """
    specs = parse_hooks(cfg)
    if not specs:
        return None
    approved = [s for s in specs if _consent(s, cfg)]
    return HookBus(approved, session_id) if approved else None
