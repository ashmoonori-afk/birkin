"""Configuration and runtime paths for birkin.

All persistent state lives under the *birkin home* directory (default
``~/.birkin``, override with ``$BIRKIN_HOME``), mirroring hermes' ``~/.hermes``
convention. Secrets are never written to the repo; API keys are read from the
environment first and only fall back to ``config.json`` when explicitly set.

This module is pure standard library and has no side effects on import beyond
reading environment variables.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# --- Defaults -------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "provider": "anthropic",  # "anthropic" | "openai" (OpenAI-compatible)
    "model": "claude-sonnet-4-6",
    "subagent_model": "claude-haiku-4-5-20251001",
    "base_url": "",  # empty -> provider default
    # Generic local-CLI runner: provider "local-cli" runs this argv with the
    # flattened prompt on stdin (configure any CLI agent without code changes).
    "cli_command": [],
    "api_key": None,  # prefer env var; only set here if you must
    "max_tokens": 4096,
    "temperature": 1.0,
    "max_turns": 24,  # safety guard on the agent tool-calling loop
    "max_depth": 2,  # subagent recursion bound
    "extra_skill_dirs": [],  # additional directories to scan for SKILL.md
    "disabled_tools": [],  # tool names the agent may NOT use (see `birkin tools`)
    "self_improve": True,  # allow the agent to write/refine skills after tasks
    # Automatic skill-ization nudges (hermes-style; no extra LLM call):
    "skill_nudge_interval": 3,   # tool iterations w/o saving a skill -> nudge (0 = off)
    "memory_nudge_interval": 6,  # user turns w/o updating memory -> nudge (0 = off)
    "web_port": 8787,
    # --- Gateway (run the agent as a service across channels) ---
    "gateway_port": 8788,
    "channels": {
        "http": {"enabled": True},
        "telegram": {"enabled": False, "token": ""},
    },
    # --- Obsidian-vault semantic memory ---
    "vault_path": "",  # empty -> <birkin_home>/vault
    # --- Nightly 04:00 self-improvement routine ---
    "nightly_hour": 4,
    "nightly_minute": 0,
    # Governs the UNATTENDED path (nightly routine's propose_action): these
    # categories are applied automatically; everything else (e.g. "cron",
    # "shell") is queued for approval (`birkin review`). Note: in an INTERACTIVE
    # chat the user is present, so run_shell executes directly — the nightly
    # routine itself is denied shell/subagent tools (see nightly.py).
    # Adjust with the REPL /permission command or `birkin permission`.
    "auto_approve": ["memory", "skill"],
    # CLI-agent (Claude Code / Codex) access level:
    #   "workspace" — writable & sandboxed to the workspace (default)
    #   "full"      — DANGEROUS: bypass all approvals + sandbox
    #                 (codex --dangerously-bypass-approvals-and-sandbox,
    #                  claude --dangerously-skip-permissions)
    "cli_access": "workspace",
    # --- Budget governor (P3 reliability). 0 = unlimited. ---
    "budget_tokens_daily": 0,
    "budget_tokens_monthly": 0,
}

PROVIDER_DEFAULT_BASE_URL = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com",
}

PROVIDER_API_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}

# Providers backed by a locally-installed, separately-authenticated agent CLI.
# These need no API key — birkin shells out to the CLI. "local-cli" runs a
# user-configured argv (config.cli_command), generalizing beyond claude/codex.
CLI_PROVIDERS = {"claude-cli", "codex-cli", "local-cli"}

# Curated, current model choices (free text is also accepted everywhere).
KNOWN_MODELS = {
    "anthropic": [
        ("claude-opus-4-7", "deepest reasoning"),
        ("claude-sonnet-4-6", "best all-round coding (default)"),
        ("claude-haiku-4-5-20251001", "fast & cheap (good for subagents)"),
    ],
    "openai": [
        ("gpt-4o", "OpenAI-compatible"),
        ("gpt-4o-mini", "OpenAI-compatible, cheaper"),
    ],
}


# --- Paths ----------------------------------------------------------------

def birkin_home() -> Path:
    """Return the birkin home directory, creating it if necessary."""
    raw = os.environ.get("BIRKIN_HOME")
    home = Path(raw).expanduser() if raw else Path.home() / ".birkin"
    home.mkdir(parents=True, exist_ok=True)
    return home


def config_path() -> Path:
    return birkin_home() / "config.json"


def user_skills_dir() -> Path:
    """User/agent-created skills (writable)."""
    d = birkin_home() / "skills"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sessions_dir() -> Path:
    d = birkin_home() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def vault_dir(cfg: dict[str, Any] | None = None) -> Path:
    """Obsidian semantic-memory vault directory."""
    raw = (cfg or {}).get("vault_path") if cfg else None
    d = Path(raw).expanduser() if raw else birkin_home() / "vault"
    d.mkdir(parents=True, exist_ok=True)
    return d


def runs_dir() -> Path:
    """Nightly/cron run summaries (surfaced on the dashboard)."""
    d = birkin_home() / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pending_dir() -> Path:
    """Proposed actions awaiting user approval."""
    d = birkin_home() / "pending"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cron_path() -> Path:
    return birkin_home() / "cron.json"


def status_path() -> Path:
    return birkin_home() / "status.json"


def ledger_path() -> Path:
    """Append-only one-line-per-run audit log."""
    return birkin_home() / "ledger.jsonl"


def activity_log_path() -> Path:
    """Rolling activity log used as nightly-routine input."""
    return birkin_home() / "activity.log"


def bundled_skills_dirs() -> list[Path]:
    """Candidate locations for skills shipped with birkin.

    Checks both the source layout (``<repo>/skills``) and the installed-wheel
    layout (``birkin/_bundled_skills``). Returns existing directories only.
    """
    pkg_dir = Path(__file__).resolve().parent
    candidates = [
        pkg_dir / "_bundled_skills",  # installed wheel (see pyproject force-include)
        pkg_dir.parent / "skills",  # editable / source checkout
    ]
    return [c for c in candidates if c.is_dir()]


# --- Load / save ----------------------------------------------------------

def load_config() -> dict[str, Any]:
    """Load config merged over defaults. Missing file -> defaults."""
    cfg = dict(DEFAULT_CONFIG)
    path = config_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
        except (json.JSONDecodeError, OSError) as exc:
            # Fail loud but non-fatal: a corrupt config should not brick the CLI.
            print(f"[birkin] warning: could not read config ({exc}); using defaults")
    return cfg


def save_config(cfg: dict[str, Any]) -> Path:
    path = config_path()
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    # config.json may hold an API key — restrict to the owner where supported.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def resolve_base_url(cfg: dict[str, Any]) -> str:
    if cfg.get("base_url"):
        return str(cfg["base_url"]).rstrip("/")
    provider = cfg.get("provider", "anthropic")
    return PROVIDER_DEFAULT_BASE_URL.get(provider, PROVIDER_DEFAULT_BASE_URL["anthropic"])


def get_api_key(cfg: dict[str, Any]) -> str | None:
    """Resolve the API key: env var first, then config file.

    CLI-agent providers (Claude Code / Codex) authenticate themselves, so a
    sentinel ``"cli"`` is returned to satisfy callers without a real key.
    """
    provider = cfg.get("provider", "anthropic")
    if provider in CLI_PROVIDERS:
        return "cli"
    env_name = PROVIDER_API_KEY_ENV.get(provider, "ANTHROPIC_API_KEY")
    return os.environ.get(env_name) or cfg.get("api_key")
