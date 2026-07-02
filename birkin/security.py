"""Security self-check — advisory warnings for risky runtime configs.

The code review surfaced that birkin's *native* agent loop (used by the
``anthropic``/``local-cli`` providers, subagents, cron "prompt" jobs and the
generic Morpheus run) executes ``run_shell`` and the file tools with **no
approval gate and no path jail** — the ``claude-cli`` path is the one that is
sandboxed by Claude Code itself. That is fine for a local REPL the user drives,
but it is a real exposure once the gateway is reachable over a channel.

Policy (chosen by the project owner): **warn and keep working**, never hard-deny
— users opt into lockdowns via ``disabled_tools``, ``fs_jail``,
``BIRKIN_HTTP_TOKEN`` and ``allowed_chat_ids``. These helpers just make the
exposure visible instead of silent. Pure standard library.
"""

from __future__ import annotations

from typing import Any

# Providers whose tools are gated by an *external* CLI (Claude Code), so the
# native ``run_shell``/file tools are not in play for them.
_GATED_PROVIDERS = {"claude-cli"}


def gateway_warnings(cfg: dict[str, Any]) -> list[str]:
    """Return advisory security warnings for running the *reachable* gateway.

    Telegram open-bot / plaintext-token warnings are emitted separately by
    ``channels.build_channels``; this covers the native-loop tool exposure and
    a couple of related opt-in lockdowns.
    """
    out: list[str] = []
    provider = str(cfg.get("provider", ""))
    disabled = set(cfg.get("disabled_tools", []) or [])

    if provider not in _GATED_PROVIDERS:
        # The non-persistent gateway path drives the native loop, where
        # run_shell has no approval gate (risk tiers only sort the inbox).
        if "run_shell" not in disabled:
            out.append(
                f"provider={provider!r} uses birkin's NATIVE tool loop, where "
                "run_shell runs with NO approval gate — a chat message reaching "
                "the gateway can execute shell. Lock it down with "
                'disabled_tools: ["run_shell", "subagent"] in config, or use '
                "provider=claude-cli (Claude Code gates every tool).")
        if not cfg.get("fs_jail"):
            out.append(
                "file tools (write_file/edit_file) are not path-confined on the "
                "native loop. Set fs_jail: true to restrict them to the "
                "workspace and ~/.birkin.")

    if cfg.get("allow_unattended_full") and cfg.get("cli_access") == "full":
        out.append(
            "allow_unattended_full is ON: the nightly Morpheus run keeps full "
            "file/shell access. (The reachable gateway itself stays sandboxed.)")

    return out


def print_gateway_warnings(cfg: dict[str, Any]) -> None:
    """Print each :func:`gateway_warnings` line with a ``[security]`` prefix."""
    for line in gateway_warnings(cfg):
        print(f"[security] {line}", flush=True)
