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

# Providers whose tool loops belong to an external CLI, so Birkin's native
# registry, disabled_tools and fs_jail do not constrain the child's own tools.
_EXTERNAL_CLI_PROVIDERS = {"claude-cli", "codex-cli", "local-cli"}


def gateway_warnings(cfg: dict[str, Any]) -> list[str]:
    """Return advisory security warnings for running the *reachable* gateway.

    Telegram open-bot / plaintext-token warnings are emitted separately by
    ``channels.build_channels``; this covers the native-loop tool exposure and
    a couple of related opt-in lockdowns.
    """
    out: list[str] = []
    provider = str(cfg.get("provider", ""))
    disabled = set(cfg.get("disabled_tools", []) or [])

    # is_auto() is exact membership, so a mistyped category allowlists nothing
    # while reading as if it were configured — the failure is invisible until
    # someone notices proposals piling up. "skills" for "skill" is the one the
    # docs themselves taught for a while.
    from .risk import CATEGORY_RISK
    unknown = [str(c) for c in (cfg.get("auto_approve") or [])
               if str(c) not in CATEGORY_RISK]
    if unknown:
        out.append(
            "auto_approve lists " + ", ".join(repr(u) for u in unknown) +
            " — no such approval category, so the entry does nothing. Known: "
            + ", ".join(sorted(CATEGORY_RISK)) + ".")

    if provider not in _EXTERNAL_CLI_PROVIDERS:
        # The non-persistent gateway path drives the native loop, where
        # run_shell has no approval gate (risk tiers only sort the inbox).
        if "run_shell" not in disabled and str(
                cfg.get("shell_approval", "manual")).lower() == "off":
            out.append(
                f"provider={provider!r} uses birkin's NATIVE tool loop and "
                'shell_approval is "off", so run_shell executes anything the '
                "model produces — a chat message reaching the gateway can run "
                'shell. Set shell_approval: "manual" (destructive commands '
                "are then queued for `birkin review`), or lock it down with "
                'disabled_tools: ["run_shell", "subagent"].')
        elif "run_shell" not in disabled:
            out.append(
                f"provider={provider!r} uses birkin's NATIVE tool loop. "
                "shellguard flags destructive run_shell commands and queues "
                "them for approval, but it is pattern-based — a seatbelt, "
                "not a sandbox. For an untrusted/company gateway prefer "
                'disabled_tools: ["run_shell", "subagent"].')
        if not cfg.get("fs_jail"):
            out.append(
                "file tools (write_file/edit_file) are not path-confined on the "
                "native loop. Set fs_jail: true to restrict them to the "
                "workspace and ~/.birkin. (birkin's own control plane — "
                "config.json, cron.json, hooks_allowlist.json, hooks/ — is "
                "refused either way; see tools/files.py.)")
    elif provider == "local-cli":
        out.append(
            "provider='local-cli' uses an external CLI tool loop. Birkin's "
            "native disabled_tools and fs_jail settings do not constrain that "
            "child, and a generic local command may have unrestricted host "
            "access unless the configured command enforces its own sandbox.")
    elif provider == "codex-cli":
        out.append(
            f"provider={provider!r} uses an external CLI tool loop. Birkin's "
            "native disabled_tools and fs_jail settings do not constrain that "
            "child; rely on the CLI's sandbox/permission policy instead.")

    if cfg.get("allow_unattended_full") and cfg.get("cli_access") == "full":
        out.append(
            "allow_unattended_full is ON: the nightly Morpheus run keeps full "
            "file/shell access. (The reachable gateway itself stays sandboxed.)")

    return out


def print_gateway_warnings(cfg: dict[str, Any]) -> None:
    """Print each :func:`gateway_warnings` line with a ``[security]`` prefix."""
    for line in gateway_warnings(cfg):
        print(f"[security] {line}", flush=True)
