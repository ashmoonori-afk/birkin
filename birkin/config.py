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
    # Automatic history compaction on the native API loop: when a request is
    # about to exceed the model's window, the middle of the conversation is
    # replaced by a summary (protected head + recent tail are kept). Also
    # retries once after a real overflow. See compaction.py. CLI providers
    # (claude-cli/codex-cli) compact their own context and ignore this.
    "auto_compact": True,
    "context_window": 200000,  # tokens; Claude family default
    # Keep answering when the primary model stops: on an auth / billing /
    # rate-limit / server / network failure, turns are served by this model for
    # `fallback_cooldown` seconds, then the primary is probed again. Both keys
    # must be set to enable it, and the fallback needs its own credentials.
    # Ignored for CLI providers (they report failures as text, not errors).
    # Typical: primary claude-oauth -> fallback anthropic (paid key) or openai.
    "fallback_provider": "",
    "fallback_model": "",
    "fallback_base_url": "",
    "fallback_cooldown": 300,
    # Tool results longer than this are written to disk and replaced by a
    # preview plus the path, so the agent can grep or page through the rest
    # instead of losing it. 0 disables. See tools/spill.py.
    "spill_threshold": 30000,
    "spill_dir": "",             # empty -> <birkin_home>/tool-results
    "spill_retention_days": 7,
    # What a line typed DURING a REPL turn does: "steer" hands it to the
    # running turn (in-flight work is kept, the model adjusts course), "kill"
    # restores the old behavior of interrupting and queueing it as the next
    # message. Esc always interrupts either way.
    "repl_typed_line": "steer",
    # Run adjacent READ-ONLY tool calls from one assistant turn concurrently
    # (see parallel.py). Writers stay sequential barriers. Set false to
    # restore strictly serial execution.
    "parallel_tools": True,
    "parallel_tool_workers": 8,
    # Gate destructive run_shell commands on the native loop
    # (shellguard.py).
    #   "manual" — prompt in the REPL; queue for approval when unattended
    #   "smart"  — let `approval_model` clear obviously-safe commands first
    #   "off"    — no gate (the pre-shellguard behavior)
    # A small set of catastrophic commands is refused in every mode.
    "shell_approval": "manual",
    # Snapshot the workspace before a mutating tool runs, into a bare git
    # store under <birkin_home>/checkpoints (never inside your project,
    # and never touching your own git history). Undo with /rollback.
    "checkpoints": True,
    # Shell scripts run on lifecycle events (see hooks.py). Shape:
    #   {"pre_tool_call": [{"matcher": "run_shell",
    #                       "command": "python ~/.birkin/hooks/guard.py"}]}
    # Events: pre_tool_call (can block), post_tool_call, pre_llm_call.
    # SECURITY: a hook is arbitrary code run with your permissions. Each
    # (event, command) is confirmed once; hooks_auto_accept skips that
    # prompt, which anyone able to write config.json can then abuse.
    "hooks": {},
    "hooks_auto_accept": False,
    "checkpoint_keep": 20,       # snapshots retained per workspace
    # Commands permanently allowed without asking (exact match or glob).
    # Grown by answering "always" at the prompt. Compound commands never
    # match, so an approval cannot carry a chained command in with it.
    "command_allowlist": [],
    "approval_model": "",        # empty -> session model, for "smart"
    "max_depth": 2,  # subagent recursion bound
    "extra_skill_dirs": [],  # additional directories to scan for SKILL.md
    "disabled_tools": [],  # tool names the agent may NOT use (see `birkin tools`)
    "self_improve": True,  # allow the agent to write/refine skills after tasks
    # Automatic self-improvement nudges (native: no extra call; Claude: skill
    # review; Codex: trusted memory review; local CLI: no review):
    "skill_nudge_interval": 3,   # tool iterations w/o saving a skill -> nudge (0 = off)
    "memory_nudge_interval": 6,  # user turns w/o updating memory -> nudge (0 = off)
    "web_port": 8787,
    # --- Gateway (run the agent as a service across channels) ---
    "gateway_port": 8788,
    # Model used only by `birkin gateway` (the always-on service). Empty -> use
    # the global "model". Set to a faster model (e.g. "sonnet") so the gateway
    # stays responsive while interactive chat can keep a heavier model.
    "gateway_model": "",
    # Codex reasoning effort for the gateway only (minimal/low/medium/high;
    # empty = model default). A chat wants speed, so 'low' trims a heavy
    # reasoning model's turn — though on some codex models the effect is
    # small (the turn latency is mostly the model itself). Ignored off codex.
    "gateway_reasoning_effort": "",
    # Keep one warm CLI process per conversation: Claude uses stream-json and
    # Codex uses its app-server protocol. Ignored by local/API providers.
    "gateway_persistent": True,
    # Tool patterns the always-on gateway may use WITHOUT an interactive
    # permission prompt (it runs headless, so an un-allowed tool would stall).
    # The gateway inherits Claude Code's MCP servers (company tools); list the
    # ones it may call here, e.g. ["mcp__claude_ai_Notion__*", "Read", "Grep"].
    # Empty -> rely on your Claude Code settings allowlist. Passed as
    # `claude --allowedTools`. See `birkin mcp` to view connected servers.
    "gateway_allowed_tools": [],
    # Opt-in: reuse ONE warm claude/codex process across REPL turns (skips the
    # ~10 s CLI cold start every message, like the gateway). Tradeoffs: routed
    # skill bodies stay in the child context until their revision changes;
    # Esc-to-interrupt is unavailable; and /retry, /undo, /compact are inert
    # (the child process owns the history, not agent.messages). /new and /model
    # correctly reset the warm process. claude-cli / codex-cli only.
    "repl_warm_session": False,
    # Headless latency knobs (measured: docs/hermes-comparison.md §6).
    # clean_hooks: run gateway claude children with the user's interactive
    # hook stack disabled (--settings disableAllHooks) — hooks cost 3-6 s per
    # turn + ~7 s of SessionStart hooks on cold start. MCP servers still load.
    "gateway_clean_hooks": True,
    # Thinking budget for gateway chat turns (MAX_THINKING_TOKENS in the
    # child). 0 = off (fast chat, −3 s TTFT); raise for reasoning-heavy bots.
    "gateway_thinking_tokens": 0,
    # Keep one pre-warmed spare claude process so the FIRST message of a new
    # conversation skips the ~28 s CLI cold start.
    "gateway_prewarm": True,
    # Auto-save every conversation turn (gateway + REPL) to sessions_dir as
    # reserved ``auto__*.json`` in the canonical format the nightly Morpheus
    # routine already consumes — so memory is extracted from real conversations
    # automatically. See transcripts.py. Disable with autosave_transcripts=false.
    "autosave_transcripts": True,
    "autosave_redact_secrets": True,   # mask obvious secrets before writing
    "autosave_max_chars": 4000,        # per-message text cap before storing
    "autosave_max_turns": 40,          # per-file cap (turns); keeps files small
    "autosave_retention_days": 30,     # delete auto__* older than this
    "autosave_max_files": 500,         # hard cap on auto__* file count
    # neurosis deep-interview ambiguity threshold (null -> resolution preset or
    # the 0.05 default; or use /neurosis --quick|--standard|--deep). Lower is
    # stricter. See skills/planning/neurosis and birkin/neurosis.py.
    "neurosis_threshold": None,
    # When true, birkin proactively runs/offers the neurosis deep-interview for a
    # COMPLEX or VAGUE work/project request that lacks clear goal/constraints/
    # acceptance — instead of guessing. Specific/simple requests are acted on
    # directly. False -> neurosis only on explicit /neurosis. See neurosis.py.
    "neurosis_auto": True,
    "channels": {
        "http": {"enabled": True},
        # Prefer the TELEGRAM_BOT_TOKEN env var over the plaintext "token" here.
        # "allowed_chat_ids" gates who may drive the bot — leave empty ONLY for a
        # private/local bot; set your chat id(s) for any shared/company use.
        # "stream": edit-stream partial replies into the chat as they arrive
        # (hermes-style perceived latency) instead of one final message.
        "telegram": {"enabled": False, "token": "", "allowed_chat_ids": [],
                     "stream": True},
    },
    # --- Obsidian-vault semantic memory ---
    "vault_path": "",  # empty -> <birkin_home>/vault
    # --- Morpheus (nightly 04:00 self-improvement routine) ---
    # Telegram chat to receive the nightly summary as a morning digest
    # (P0-3). Empty = no delivery. Honors the outbound allowlist and the
    # [SILENT] convention; appends a pending-approvals count when relevant.
    "morpheus_deliver_chat_id": "",
    "workspace_roots": [],
    # Hourly reaper: kill orphaned claude/codex->node subprocesses left behind
    # by a birkin process that died ungracefully. Only reaps children whose
    # OWNER process is gone — a live birkin's sessions are never touched. See
    # procreg.py. Set false to disable.
    "reaper_enabled": True,
    # The routine was renamed from "nightly" to "morpheus" (Greek god of
    # dreams — it runs while you sleep). The legacy keys ``nightly_hour`` /
    # ``nightly_minute`` are honored as fallbacks by readers and migrated
    # on next ``save_config``; new installs only see the canonical names.
    "morpheus_hour": 4,
    "morpheus_minute": 0,
    # Governs the UNATTENDED path (nightly routine's propose_action): these
    # categories are applied automatically; everything else (e.g. "cron",
    # "shell") is queued for approval (`birkin review`). Note: in an INTERACTIVE
    # chat the user is present, so run_shell executes directly. Native/Claude
    # Morpheus excludes direct shell/subagent tools; Codex uses its own tools in
    # a read-only sandbox by default; local CLI permissions remain user-managed.
    # Adjust with the REPL /permission command or `birkin permission`.
    # SECURITY: do NOT add "shell" here for an unattended/company agent. A
    # shell-typed "cron" proposal is treated as shell and will NOT auto-apply
    # unless "shell" is auto-approved — it is queued for `birkin review` instead.
    "auto_approve": ["memory", "skill"],
    # CLI-agent (Claude Code / Codex) access level:
    #   "workspace" — writable & sandboxed to the workspace (default)
    #   "full"      — DANGEROUS: bypass all approvals + sandbox
    #                 (codex --dangerously-bypass-approvals-and-sandbox,
    #                  claude --dangerously-skip-permissions)
    "cli_access": "workspace",
    # Opt-in (default False): let Codex Morpheus honor cli_access "full" instead
    # of read-only. Claude Morpheus keeps its workspace allowlist; local CLI owns
    # its permissions. The reachable gateway is unaffected.
    "allow_unattended_full": False,
    # --- Budget governor (P3 reliability). 0 = unlimited. ---
    "budget_tokens_daily": 0,
    "budget_tokens_monthly": 0,
    # Seconds to wait for a CLI-agent subprocess (claude/codex/local-cli) before
    # giving up; surfaced so users can tune long-running agents. See llm.py.
    "cli_timeout": 300,
    # Opt-in: when true, a NEW memory note with no prior/provided source is
    # refused. False -> evidence is not required. See memory.py.
    "evidence_required": False,
    # --- v2 components (docs/v2.md). All opt-in / additive. ---
    # #6 Hyperplan: how many adversarial critics attack a plan before execution.
    "critique_agents": 3,
    # #5 Boulder: resumable checkbox-plan execution caps. See boulder.py.
    "boulder_max_iters": 100,
    # Opt-in path jail for the native file tools (write_file/edit_file/read_file):
    # when true, confine them to the workspace + ~/.birkin and reject absolute /
    # ".." escapes. Default False to preserve behavior. See tools/files.py.
    "fs_jail": False,
    # Opt-in supply-chain guard: verify the upstream commit signature before
    # `update` fast-forwards. Default False (requires a signed-commit upstream).
    "update_verify_signature": False,
}

PROVIDER_DEFAULT_BASE_URL = {
    "anthropic": "https://api.anthropic.com",
    "claude-oauth": "https://api.anthropic.com",
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

# Providers that authenticate to the Anthropic Messages API *in-process* with a
# Claude subscription OAuth token (the `claude` CLI login) — free (no paid API
# key) and fast (no `claude -p` subprocess, so no per-message Claude Code hooks).
# birkin runs its own tool loop over this transport. See ``oauth.py``.
OAUTH_PROVIDERS = {"claude-oauth"}

# Curated, current model choices (free text is also accepted everywhere).
KNOWN_MODELS = {
    "anthropic": [
        ("claude-opus-4-8", "deepest reasoning"),
        ("claude-sonnet-5", "best all-round coding (default)"),
        ("claude-haiku-4-5-20251001", "fast & cheap (good for subagents)"),
        ("claude-fable-5", "Fable 5"),
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


def skill_dirs(cfg: dict[str, Any]) -> list[tuple[Path, str]]:
    """The ordered (directory, source-label) list scanned for SKILL.md.

    Single source of truth for the skill search path — bundled dirs first,
    then any ``extra_skill_dirs`` from config, then the writable user dir
    (which shadows bundled skills of the same name).
    """
    dirs: list[tuple[Path, str]] = [(d, "bundled") for d in bundled_skills_dirs()]
    for extra in cfg.get("extra_skill_dirs", []) or []:
        dirs.append((Path(extra).expanduser(), "extra"))
    dirs.append((user_skills_dir(), "user"))
    return dirs


# --- Load / save ----------------------------------------------------------

def load_config() -> dict[str, Any]:
    """Load config merged over defaults. Missing file -> defaults.

    Legacy ``nightly_hour`` / ``nightly_minute`` keys are silently migrated
    into ``morpheus_hour`` / ``morpheus_minute`` when only the old keys are
    present in the saved file, so configs written before the rename keep
    working unchanged.
    """
    cfg = dict(DEFAULT_CONFIG)
    saved: dict[str, Any] = {}
    path = config_path()
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                saved = raw
                cfg.update(saved)
        except (json.JSONDecodeError, OSError) as exc:
            # Fail loud but non-fatal: a corrupt config should not brick the CLI.
            print(f"[birkin] warning: could not read config ({exc}); using defaults")
    # Deep-merge nested sub-sections so setting one entry doesn't drop the
    # defaults for the others (e.g. saving only channels.telegram must keep the
    # default channels.http). A plain dict.update() replaces the whole sub-tree.
    for nk in ("channels",):
        base, sv = DEFAULT_CONFIG.get(nk), saved.get(nk)
        if isinstance(base, dict) and isinstance(sv, dict):
            merged = {k: (dict(v) if isinstance(v, dict) else v)
                      for k, v in base.items()}
            for k, v in sv.items():
                merged[k] = ({**merged[k], **v}
                             if isinstance(v, dict) and isinstance(merged.get(k), dict)
                             else v)
            cfg[nk] = merged
    # Migrate legacy keys (in-memory only). We look at the *saved* data so we
    # don't overwrite a real ``morpheus_hour`` with the static default just
    # because the default is in the merged ``cfg``.
    if "nightly_hour" in saved and "morpheus_hour" not in saved:
        cfg["morpheus_hour"] = saved["nightly_hour"]
    if "nightly_minute" in saved and "morpheus_minute" not in saved:
        cfg["morpheus_minute"] = saved["nightly_minute"]
    # Validate the privilege level: an unknown value silently degrades to the
    # safe default rather than mis-routing to the dangerous "full" path.
    if cfg.get("cli_access") not in ("workspace", "full"):
        cfg["cli_access"] = "workspace"
    return cfg


def save_config(cfg: dict[str, Any]) -> Path:
    # config.json may hold an API key, so write atomically (mirrors
    # store._write_json): write a temp sibling, restrict it before it is
    # briefly visible, then os.replace() for an atomic swap. A crash mid-write
    # then cannot truncate the live config.
    path = config_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        try:  # restrict the temp file too, before it is briefly visible
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    except OSError:
        try:  # don't leave a partial .tmp behind on a failed write
            tmp.unlink()
        except OSError:
            pass
        raise
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

    OAuth providers (``claude-oauth``) resolve the Claude subscription OAuth
    token from the ``claude`` CLI login (``~/.claude/.credentials.json``),
    returning ``None`` when the user is not logged in so callers can prompt.
    """
    provider = cfg.get("provider", "anthropic")
    if provider in OAUTH_PROVIDERS:
        from . import oauth
        return oauth.resolve_token()
    if provider in CLI_PROVIDERS:
        return "cli"
    env_name = PROVIDER_API_KEY_ENV.get(provider, "ANTHROPIC_API_KEY")
    return os.environ.get(env_name) or cfg.get("api_key")
