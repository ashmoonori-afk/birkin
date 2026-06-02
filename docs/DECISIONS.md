# birkin — Decision Log (ADRs)

Lightweight architecture decision records. Each entry: context, decision,
rationale, alternatives considered, status. Newest decisions may supersede
older ones (noted inline).

> Last updated: 2026-06-02

---

## ADR-035 — Esc aborts the in-flight REPL turn

**Context.** The REPL had only Ctrl-C (quit/interrupt). Users wanted to **abort a
running reply with Esc** (like Claude Code) without killing the session — but
while the agent works the main thread is blocked inside `session.ask`, so nothing
reads the keyboard, and the free path is a *blocking* `claude`/`codex` subprocess.

**Decision.** A cooperative abort flag threaded end-to-end, plus a background Esc
listener:
- `Session.abort` is a `threading.Event` (cleared before each `ask`). `Agent.run`
  threads it into the loop: checked **between turns** (returns "[birkin] aborted.")
  and passed into `LLMClient.complete`.
- `LLMClient`: the Anthropic SSE reader stops between events on abort (closes the
  response); the CLI runners now go through a shared `_run_cli_capture` that uses
  `Popen` + drain threads (no pipe-buffer deadlock) and **polls so the child is
  killed** on abort or `cli_timeout` (replaces the old blocking `subprocess.run`).
- `birkin/abortkey.py`: a daemon **Esc listener** (termios+select on POSIX,
  msvcrt on Windows) that fires a callback on `0x1b`; **no-op when stdin is not a
  TTY** (piped runs / tests unaffected). The REPL starts it around `ask`, and on
  Esc sets `session.abort` + stops the spinner; stops the listener in `finally`.

**Alternatives.** Sending SIGINT to self on Esc (reuses Ctrl-C handling) was
rejected — unreliable on Windows (this is a Windows-primary user) and it would
also tear down more than the turn. The cooperative flag + subprocess-kill is
cross-platform and scoped to the current reply.

**Status.** Done; REPL-only (the gateway is a headless service). 7 new tests
(agent between-turn abort, `_run_cli_capture` kills a sleeping child promptly,
listener no-ops off-TTY); 489 pass offline. Limitation: abort is checked between
SSE events / by polling the subprocess, so it is prompt but not instantaneous;
tool execution mid-step finishes before the next between-turn check.

---

## ADR-034 — Codex-backend compatibility

**Context.** birkin supports several backends (`CLI_PROVIDERS = {claude-cli,
codex-cli, local-cli}` + API providers), but parts of the runtime had hardened
around `claude-cli`. Running on the **codex** model surfaced gaps.

**Decision.** Make the provider-generic paths actually provider-generic, without
faking codex-only plumbing we can't verify:

- **Morpheus routing (real bug).** `run_once` routed *every* `CLI_PROVIDERS`
  member to `_run_claude_morpheus`, which spawns a `ClaudeStreamSession` — so a
  user on **codex** had `claude` silently spawned. Now only `claude-cli` takes
  the sandboxed Claude+birkin-MCP path; codex-cli / local-cli / API providers use
  the generic agent-loop morpheus (`_run_birkin_morpheus`, restricted registry,
  no shell/subagent). Also: `run_once` now **downgrades `cli_access:"full"` →
  `"workspace"`** for the unattended run regardless of provider (the claude path
  already did this internally; now codex/local are protected too).
- **Gateway `/models` (real bug).** It was claude-centric (`opus/sonnet/haiku`,
  rejecting anything not `claude-*`). Now **provider-aware**: claude-cli keeps the
  validated set; codex-cli shows codex suggestions and **passes any model id
  through** (codex validates `-m` itself); API/other providers pass through too.
- **Verified already-fine:** `llm._run_codex` (one-shot `codex exec
  --skip-git-repo-check -o <file> [-m model]`) works; `birkin model` already
  offers codex (`models.detect_cli_agents`); `runtime.build_dry_run_packet` and
  the CLI system prompt + persona + neurosis note are provider-generic.

**Honest limitation (not a bug).** The **warm persistent gateway** path
(`ClaudeStreamSession`, stream-json) stays **claude-cli-only** — `codex exec` is
one-shot and has no equivalent persistent stream protocol birkin uses. So the
codex gateway runs **non-persistent** (correct, just cold each turn, not ~3s
warm). A persistent codex session and a sandboxed-MCP codex morpheus (wiring
birkin-MCP into `codex`) are future work (need verified codex MCP flags — not
fabricated here).

**Status.** Done; morpheus routing + cli_access clamp + provider-aware `/models`;
5 new tests; 437 pass offline (1 unrelated `test_web` socket flake, green in
isolation).

---

## ADR-033 — Telegram replies render Markdown (GFM → Telegram HTML)

**Context.** The gateway agent emits GitHub-flavored Markdown (`**bold**`,
`# headings`, `|` tables, fenced code, lists, links). The Telegram channel sent
it via `sendMessage` with **no `parse_mode`** (`telegram.py:130`, `text=reply[:4000]`),
so it arrived as raw text — literal `**`, `|---|`, `##` — and long replies were
silently truncated at 4000 chars. The user reported markdown "not rendering" in
Telegram.

**Decision.** Convert the agent's GFM to the small HTML subset Telegram renders
and send with `parse_mode="HTML"`. New module `gateway/channels/tg_format.py`
(pure stdlib): `to_html()` maps bold/italic/strike/inline-code/fenced-code/
headings/links/bullets/blockquotes, and — since Telegram has no `<table>`/heading
tags — renders pipe tables as an **aligned monospace `<pre>`** (CJK-width aware
via `unicodedata.east_asian_width`, so Korean tables line up) and headings as
bold. `split()` chunks output under Telegram's 4096 limit on safe boundaries,
never tearing a `<pre>`/`<blockquote>` (oversized ones split into multiple valid
same-tag blocks). The channel sends each chunk as HTML; if Telegram rejects one
(`ok:false`/HTTPError), that chunk **degrades to plain text** via `to_plain()` —
so a converter edge case can never drop or duplicate a reply.

**Why HTML, not MarkdownV2.** HTML mode escapes only `& < >` (`"` too, inside
`href`); MarkdownV2 must escape ~18 characters everywhere and 400s on a stray
`.`/`-`/`!` — fragile for arbitrary model output.

**Adversarial review fixes (before commit).** A reviewer found three real
400-triggers, all fixed + regression-tested: (1) a `"` in a link URL broke the
`href` attribute → dedicated `_esc_attr`; (2) crossing/overlapping emphasis
(`***x***`, `**a _b** c_`) emitted interleaved tags Telegram rejects → `***`/`___`
handled as bold+italic and a `_balance_emphasis` net strips emphasis (keeping
text) whenever tags would cross; (3) `split()` tore a long multi-line
`<blockquote>` → it is now protected like `<pre>`. Known LOW (unfixed): a literal
`)` inside a link URL truncates it (markdown-regex limitation).

**Status.** Done; `tg_format` + channel wiring + 20 tests. 432 tests pass offline.
Localized to the Telegram channel — REPL/HTTP render markdown themselves
(`ui.render_markdown`), so they are untouched.

---

## ADR-032 — Session-review hardening (free+fast gateway + Neurosis + autosave)

**Context.** A full multi-agent code review of this session's work (free+fast
persistent gateway, Neurosis, auto-save→memory, MCP, `/models`, word-wise line
editing) was run against the canonical tree. Verdict: **ship-with-fixes — zero
CRITICAL**; 9 HIGH (2 self-retracted as false-positives), the rest MEDIUM/LOW.

**Decision.** Apply the confirmed HIGH fixes (minimal diffs, no architecture
change), each with a regression test where behavior changed:

- **`proc.cli_argv` Windows injection guard.** `cmd /c` re-parses shell
  metacharacters *inside* each discrete arg, so a value like `foo & calc`
  smuggled through `birkin mcp add …` could chain a second command. Now rejects
  args containing `& | < > ^` on Windows (the program name is exempt; POSIX
  argv is shell-free and unaffected). Adds to ADR-029's security posture.
- **`neurosis.resolve_threshold`** now *raises* on an out-of-range explicit
  override `(0,1]` instead of silently falling through to config/default — an
  explicit flag must win or fail loudly, never be dropped.
- **`neurosis.seed_state` resume** re-applies an explicit `--quick/--standard/
  --deep` (or `--threshold`) to an *active* interview (rebuilt immutably +
  persisted) instead of ignoring it; a plain resume still keeps the prior tuning
  and never clobbers in-progress rounds (ADR-031 invariant preserved).
- **`transcripts._maybe_enforce_retention`** throttle + sweep now run under a
  non-blocking `threading.Lock`, so concurrent gateway channel threads can't
  double-sweep and over-delete; a turn whose sweep slot is taken returns at once.
- **`llm` OAuth `mcp_` strip** rebuilds the result blocks immutably (house
  immutability rule) instead of mutating returned content in place.
- **`inline_complete` Ctrl-U/Ctrl-K** now bound to the **current logical line**
  (not the whole buffer), so a kill on line 2 no longer wipes line 1 — matching
  the documented "delete to line start/end" semantics for multiline input.
- **`inline_complete.prompt_with_completion`** clears module `_pushback` at
  session start (a paste ending in a control byte could otherwise fire into the
  next prompt) and restores the Kitty Keyboard Protocol in a `finally` so a
  raised loop can't leave terminal mode enabled.
- **gateway `/models`** also updates in-memory `self.cfg` after persisting, so
  state is consistent even if the scheduled hard-restart re-exec never happens.
- **gateway `restart()`** gains an `assert self._lock.locked()` tripwire to make
  its "callers hold the lock" invariant fail loudly in dev (it is held today).

**Alternatives.** For the Windows guard, resolving the `.cmd` shim via
`shutil.which` + `shell=False` was considered but is a larger change; rejecting
metacharacters is sufficient defense-in-depth for trusted-operator input.

**Status.** Done; 8 HIGH fixed (1 doc-only accepted), 2 false-positives
dismissed. The two false-positives: `str.startswith(tuple)` is valid Python; and
`build_session`'s first turn is *not* persona-less (every turn, including the
first, re-injects persona + Neurosis via `ask()`/`refresh_system_prompt()`).

**MEDIUM/LOW follow-up pass.** A second 19-agent triage verified every MEDIUM/LOW
finding against current code (real / false-positive / already-fixed / wont-fix).
**16 confirmed real, fixed** (minimal diffs, tests where behavior changed):
- *config.py* — `save_config` now writes config.json atomically (tmp + chmod +
  `os.replace`), mirroring `store._write_json`, so a crash can't truncate the
  API-key-bearing file; added `cli_timeout`/`evidence_required` to DEFAULT_CONFIG.
- *transcripts.py* — `_prep` masks BEFORE truncating, closing a boundary leak
  where a secret straddling `max_chars` lost its suffix and survived un-redacted.
- *approvals.py* — cron `hour`/`minute` are clamped (default on garbage, range
  0-23 / 0-59) instead of raising or storing a time that can't fire.
- *store.py* — `_write_json` temp name is now per-process unique (pid + uuid), so
  concurrent writers to one path don't collide on the temp.
- *neurosis.py* — collision-resistant `_slug` (hash suffix on truncation);
  `start_prompt` no longer leaks the absolute bundled-skill path into the
  model/transcript; `auto_trigger_note` honors `BIRKIN_HOME`.
- *gateway/core.py* — `/neurosis` seed read-modify-write moved under the lock
  (TOCTOU); `match_command` returns no stale arg for hard-restart.
- *persona.py* — `write_soul` cleans its temp on a failed replace (Windows
  window). *runtime.py* — dry-run packet now mirrors a real turn (persona +
  Neurosis note). *mcp_server.py* — line-size guard measures bytes, not chars.
  *oauth.py* (parked) — refresh failure reason surfaced under `BIRKIN_DEBUG`.
- *inline_complete.py* / *SKILL.md* — doc corrections (apply_event is a mutating
  builder; threshold precedence includes the resolution preset step).
Dismissed: 6 false-positives (e.g. mcp_server stdout already isolated; 0600 temp
configs already non-sensitive) and 8 wont-fix LOW (pre-existing / out-of-scope).
**412 tests** pass offline (9 new); 2 unrelated `test_web` socket flakes pass on
isolated re-run.

---

## ADR-031 — Neurosis: Socratic deep-interview (ported from gajae-code)

**Context.** The user wanted birkin to run a "deep interview" — the structure from
gajae-code (Yeachan-Heo/gajae-code), which forked the Ouroboros idea: turn a vague
idea into a crystal-clear spec via Socratic questioning with **mathematical
ambiguity gating** before any execution. Codename **Neurosis** (obsessive clarity,
sibling to Morpheus).

**Studied structure (gajae-code).** Two layers: (1) a **SKILL.md** that IS the
protocol the agent executes — one question at a time aimed at the weakest clarity
dimension (Goal/Constraints/Success, +Context for brownfield), ambiguity =
`1 − Σ(dim×weight)`, refuse to proceed until `≤ threshold`; Round 0 topology lock,
ontology convergence tracking, challenge modes (Contrarian R4 / Simplifier R6 /
Ontologist R8), soft caps (R10/R20), resumable state, spec crystallization, then an
approval-gated execution bridge. (2) A thin **runtime** that does NOT run the
interview — it resolves the threshold (`--quick 0.6/--standard 0.5/--deep 0.35`,
default 0.05), seeds a state file, and hands off to the skill; plus a mutation guard.

**Decision.** Faithful port, birkin-adapted:
- **`skills/planning/neurosis/SKILL.md`** — the full protocol (topology + ontology +
  challenge modes + ambiguity math + spec + resume), with birkin's house rule:
  **interview in Korean, final spec in English**. "Ask one question" maps to a
  birkin chat turn, so it works in the REPL and over Telegram unchanged.
- **`birkin/neurosis.py`** — the thin runtime: `resolve_threshold` (override >
  config `neurosis_threshold` > resolution preset > 0.05), `_slug`, `seed_state`
  (resumable state in `~/.birkin/neurosis/<slug>.json`, reusing `store._write_json`),
  `seed_or_resume` (idea → new; no idea → resume most recent active; **re-seeding the
  same idea resumes, never clobbers**), `skill_path`, and `start_prompt` (the kickoff
  the surfaces feed the agent).
- **Surfaces:** `/neurosis [--quick|--standard|--deep] <idea>` in the REPL and the
  gateway (Telegram), and `birkin neurosis "<idea>"` CLI (seeds + handoff). The
  gateway runs the kickoff as a normal turn (works persistent + non-persistent) and
  logs/auto-saves a friendly `display_text`, not the giant kickoff prompt.
- **Birkin-izations:** spec → `~/.birkin/specs/`, with an approval option to persist
  it to memory for Morpheus; **Telegram works**; the approval bridge is "birkin
  executes on approval / save to memory / refine / stop" (no `.gjc`/ralplan/team);
  the mutation-guard becomes a prompt rule ("no side effects until approved").
- **Auto-trigger (`neurosis_auto`, default true):** `neurosis.auto_trigger_note`
  is appended to the gateway + REPL system prompts so the agent **proactively runs
  or offers** the interview for a complex/vague work/project request that lacks
  clear goal/constraints/acceptance, and acts directly on specific/simple ones —
  mirroring gajae's staged routing, but always under the agent's judgment (prompt-
  steered, not a deterministic keyword gate). The skill self-derives state/spec
  paths + threshold when auto-invoked (no launcher).

**Status.** Done; skill + runtime + 3 surfaces + 2 config flags + auto-trigger;
15 tests; 386 total
pass. Code-reviewed (fixed: gateway flag parsing, re-seed data-loss, an immutability
nit). On-the-wire interview driven by the agent following the skill across turns.

---

## ADR-030 — Auto-save conversation transcripts → automatic memory extraction

**Context.** The nightly **Morpheus** routine already extracts memory from
session files in `sessions_dir()` (`_gather_sessions` globs `*.json`), but the
ONLY writer was the manual `/save` command — so almost nothing landed there. The
warm persistent gateway made it worse: the conversation lives inside the `claude`
process, so nothing was on disk at all. Memory extraction had no material.

**Decision.** Add `birkin/transcripts.py` — `append_turn(channel, chat_id, user,
reply)` persists each turn to a per-`(channel, chat, UTC-day)` file
`auto__<channel>__<chat>-<hash>__<day>.json` in `sessions_dir()`, in the EXACT
canonical format `/save` writes and `selfimprove.transcript_from_messages`
consumes — so Morpheus extracts from it nightly with **zero consumer changes**.

- **Turn-pair accumulation, not `agent.messages` dump.** In the persistent
  gateway `claude` holds the history and birkin only sees `(user_text, reply)`;
  appending that pair is correct for every path (persistent/non-persistent
  gateway + REPL). (The design workflow's first pass got this wrong by grounding
  against the old `marketing` tree; corrected here.)
- **Hooks:** `gateway/core.py` `handle()` (after the reply, outside the global
  lock — so a per-conversation lock guards the read-modify-write) and `repl.py`
  (one file per process run). Commands (`/help`, `/new`, `/restart`, …) return
  early and are never saved.
- **Reserved `auto__` namespace:** hidden from `/sessions`, rejected by `/save`,
  so it never collides with manual saves; `_gather_sessions` still globs `*.json`
  and picks them up.
- **Extraction = the existing nightly Morpheus** (free, sandboxed Claude + birkin
  MCP). On-demand `/new`/idle extraction was deliberately CUT from v1 (the review
  found wiring + duplication-amplification + pile-up issues); if added later it
  should reuse the already-scoped `selfimprove.reflect_and_learn`, not a full
  nightly pass.

**Security (from the adversarial + security review).**
- **Trust gate (was the CRITICAL finding):** auto-save fires only for *trusted*
  conversations — `Gateway._autosave_trusted`. Telegram is trusted only when
  `allowed_chat_ids` is set; an OPEN bot's strangers are NOT persisted or
  memorized (prevents memory-poisoning). REPL + loopback HTTP are local → trusted.
- **Secret redaction** before write (default on): Anthropic/OpenAI/Google/GitHub/
  Slack/AWS keys, Telegram bot tokens, `Bearer` headers, PEM private keys, and
  labeled `key:`/`password:` values to end-of-line. Operates on copies (never
  mutates live messages).
- **Per-message char cap** (`autosave_max_chars`, 4000) + per-file turn cap
  (`autosave_max_turns`, 40) + retention (`autosave_retention_days` 30,
  `autosave_max_files` 500, throttled, mtime-keyed sort) bound disk + the shared
  20k `_gather_sessions` budget + flood abuse.
- **At rest:** files (and now the temp file) are `0o600` via `store._write_json`.

**Accepted residuals (documented, not v1 blockers).**
- On Windows `chmod 0o600` is partial; confidentiality relies on the user-profile
  NTFS ACL — keep `$BIRKIN_HOME` off shared paths (same caveat as `config.json`).
- The local HTTP channel is loopback + Host-checked but unauthenticated; on a
  shared host, secure it separately before enabling autosave there.
- A conversation crossing UTC midnight splits into two day-files (both extracted).

**Status.** Done; `birkin/transcripts.py` + hooks + 6 config flags; 22 tests
(format/morpheus-compat, concurrency, redaction, retention cap with tied mtimes,
trust gate, char cap); 371 total pass. Config opt-out: `autosave_transcripts=false`.

---

## ADR-029 — Company-grade security hardening

**Context.** A multi-agent security review of this session's new code flagged
risks for an unattended, company-deployed agent.

**Decisions / fixes.**
- **cron→shell laundering (CRITICAL).** An auto-approved `cron` could carry a
  `type:"shell"` payload past the *separate* `shell` gate → unattended arbitrary
  code execution if an operator ever trusted `cron`. `approvals.propose` now
  refuses to auto-apply a shell-typed cron unless `shell` itself is auto-approved;
  it queues it for `birkin review` instead. The default `auto_approve`
  (memory, skill) was already safe.
- **Gateway never runs `--dangerously-skip-permissions` (HIGH).** The gateway is
  reachable over channels, so `cli_access:"full"` is forced down to `workspace`
  for the gateway path (with a printed warning). A chat message can never reach a
  fully-permissioned Claude process.
- **Telegram access control (HIGH).** `channels.telegram.allowed_chat_ids` gates
  who may drive the bot; an empty list prints a loud "anyone can drive it"
  warning at startup.
- **Telegram token off-disk (MEDIUM).** The token is read from
  `TELEGRAM_BOT_TOKEN` / `BIRKIN_TELEGRAM_TOKEN` first; a plaintext token in
  `config.json` prints a migrate/rotate warning.
- Morpheus stays sandboxed (ADR-028): `Read/Glob/Grep` + `mcp__birkin__*`, no Bash.

**Accepted residuals (documented).**
- On Windows, `chmod 0o600` on the OAuth credentials file and the system-prompt
  temp file is a no-op; `%TEMP%` is per-user so practical exposure is limited.
  Shared/CI Windows hosts should set an explicit owner-only ACL.
- `birkin mcp <args>` forwards args to `claude mcp` via `cmd /c` — trusted-operator
  input only; do not wire `birkin mcp add` to remote input on Windows.
- The local HTTP channel binds `127.0.0.1` with a Host-header check (loopback-only).

**Status.** Fixes done; 328 tests pass (incl. cron-gate + access-control tests).
Secrets are never logged or placed in argv (verified).

---

## ADR-028 — Morpheus on the free path: birkin-as-MCP-server + sandboxed Claude

**Context.** Morpheus (the nightly self-improvement routine) needs birkin's
structured tools — the memory-OS (write/search with frontmatter + versioning),
skill authoring, and the approval-gated `propose_action`. On the free claude-cli
backend, `claude` runs its OWN tools, so (1) birkin's structured tools were not
available to it, and (2) the intended unattended sandbox (no shell/subagent) was
**bypassed** — `claude` ran with `acceptEdits` and full tools, a real risk for an
unattended company agent.

**Decision.** birkin now *provides* its tools over MCP — `birkin/mcp_server.py`,
a stdlib stdio JSON-RPC server (`birkin mcp-serve`) exposing only safe,
reversible, LLM-free tools: memory (remember / write / search / get / link),
create/improve_skill (the body is authored by the caller, not a birkin LLM call),
and propose_action (→ the approval queue). Morpheus runs a **sandboxed** Claude
Code session: `--mcp-config <birkin>` + `--strict-mcp-config` +
`--allowedTools "Read,Glob,Grep,mcp__birkin__*"` — **no Bash, no arbitrary file
writes**. The nightly pass is therefore free (subscription), structured (birkin's
tools), and secure (cannot run shell). The API-key path keeps birkin's own
restricted agent loop. Verified: `claude` connects to the birkin MCP server
(`status: connected`) and sees all 8 `mcp__birkin__*` tools.

**Rationale.** This inverts ADR-027 (birkin *consumes* MCP) into birkin
*providing* MCP — the one mechanism that gives Claude Code access to birkin's
structured, auditable tools while staying free, and it doubles as a per-tool
security boundary (the `--allowedTools` allowlist) for unattended runs.

**Status.** Done. MCP server + `mcp-serve` + provider-aware sandboxed Morpheus;
321 tests pass. The gateway can opt into the same birkin MCP (memory-in-chat) via
`gateway_allowed_tools` + an `--mcp-config` flag (follow-up).

---

## ADR-027 — Company MCP tools: inherit Claude Code's MCP, surface it in birkin

**Context.** As a company agent, the gateway must connect "naturally" to the
programs people use (Notion, Google Drive/Gmail/Calendar, internal HTTP/stdio
servers) via MCP — kept lightweight.

**Decision.** Because the gateway runs on a warm Claude Code process (ADR-026),
it **inherits Claude Code's MCP servers natively** — no new protocol code.
Verified: the headless stream-json session's `system/init` event lists every
configured MCP server and exposes their tools (here: 19 MCP tools; Notion +
pencil connected, Google connectors after a one-time auth). birkin adds only a
thin surface in `birkin/mcp.py`: `birkin mcp …` (pass-through to `claude mcp`,
full feature set) and `/mcp` (list with connection status), plus a
`gateway_allowed_tools` config passed as `claude --allowedTools` so the
unattended gateway may call company MCP tools without an interactive permission
prompt.

**Rationale.** Reusing Claude Code's MCP is the lightest path (zero re-implemented
protocol) and gives the broadest, best-maintained connector set. birkin's job is
discoverability + headless permission, not rebuilding MCP. Aligns with "as
lightweight as possible."

**Alternatives.** A from-scratch stdlib MCP client in birkin's own tool loop —
rejected as heavier and redundant for the (default) Claude-Code-backed gateway;
it remains an option only if a non-Claude provider becomes the default.

**Status.** Done. `birkin mcp list` works; `/mcp` shows status; 300 tests pass.
Google connector auth (Drive/Gmail/Calendar) is the user's one-time `claude` step.

---

## ADR-026 — Free + fast: persistent Claude Code (stream-json), not direct-API OAuth

**Context.** Gateway replies were ~21s for a one-line answer. Two candidate
"free + fast" paths were investigated against the live Anthropic API:

1. **Direct API with the Claude OAuth token** (read `~/.claude/.credentials.json`,
   send `Authorization: Bearer` + `anthropic-beta: claude-code-20250219,oauth-2025-04-20`
   + `user-agent: claude-cli/<ver>` + the "You are Claude Code…" system prefix —
   the hermes-agent technique). Verified working at the protocol level
   (`count_tokens` → 200 for opus-4-8 / sonnet-4-6 / haiku-4-5).
   **But** `/api/oauth/usage` shows a separate `seven_day_oauth_apps` window and
   `extra_usage.is_enabled=false`: Anthropic meters *third-party* OAuth-app API
   use as **paid `extra_usage`**, distinct from Claude Code subscription billing.
   So a generation request is rejected `400 "You're out of extra usage."` even
   with the subscription only 3% used. **Direct-API OAuth is NOT free.**
2. **`claude -p` (real Claude Code)** — billed to the subscription = **free**,
   and confirmed working. It was slow only because a broken global hook
   (`clawd-on-desk`) taxed every invocation ~14-18s (per-event `wmic` PID
   resolution; the Clawd app wasn't even running).

**Decision.** Stay on the **free** Claude-subscription path and make it fast:
- (a) Removed the broken global `clawd-on-desk` hooks from `~/.claude/settings.json`
  (backed up). `claude -p`: 21s → ~8s; ttft 7.5s → 1.9s. Affects all `claude` use.
- (b) Added `birkin/claude_session.py`: **one warm `claude` process per
  conversation** over `--input-format stream-json --output-format stream-json`.
  Cold-start (plugins/MCP) is paid once; warm turns are ~model-time (~3s). The
  process keeps Claude Code's own conversation context, so only the new turn is
  sent. Wired into the gateway behind `gateway_persistent` (default true), for
  the `claude-cli` provider.
- The direct-API OAuth code (`birkin/oauth.py`, the `claude-oauth` provider in
  `llm.py`/`config.py`) is **parked** — kept for the read-only usage check
  (`/api/oauth/usage`) and as a future option if the user ever enables
  `extra_usage`. It is NOT the default and cannot bill silently.

**Rationale.** Honours the hard constraint "stay on OAuth / free." Header-spoofing
the direct API does not make Anthropic bill it as Claude Code (verified), so the
only free path is Claude Code itself; the win is removing per-message overhead
(broken hook) and per-message cold-start (persistent process). Result: 21s →
~3s warm, free, and lighter than hermes (stdlib subprocess pipe, no SDK).

**Alternatives.** Enable a small paid `extra_usage` budget for the fast direct API
(rejected — violates the free constraint). Disable hooks per-call via flags
(`--bare` breaks login; `--settings '{"hooks":{}}'` is union-merged and cannot
clear user hooks — verified).

**Status.** (a) and (b) done + verified (live: cold ~8s, warm ~3s, context kept;
287 tests pass). Streaming partial tokens to channels is a deferred polish.

---

## ADR-001 — Rebuild as a lightweight, zero-dependency core

**Context.** The previous birkin (v0.8) was ambitious: a 65-node workflow graph
engine, FastAPI gateway with 66 endpoints, 9 LLM providers, 724+ tests. The new
goal is explicitly "as lightweight as possible," CLI-first, single-command.

**Decision.** Rebuild from scratch with a minimal core. Preserve the **memory
system** (per owner instruction) but overhaul everything else.

**Rationale.** A small surface is easier to run anywhere, reason about, and let
the agent self-modify. It matches the "Minimal surface" principle.

**Alternatives.** Refactor the existing codebase in place — rejected; the owner
authorized a full overhaul and the new direction diverges substantially.

**Status.** Accepted.

---

## ADR-002 — Python, standard library only

**Context.** Need cross-platform (macOS/Linux/Windows), single-command,
lightweight. hermes is Python; openclaw is Node.

**Decision.** Python ≥ 3.10, **no runtime dependencies** — stdlib only
(`urllib`, `http.server`, `sqlite3` if needed, `argparse`, `html.parser`,
`threading`).

**Rationale.** The owner chose Python (`스택은 python으로`). Stdlib-only means
trivial install, no dependency drift, and easy self-modification. `urllib`
handles the LLM HTTP/SSE; `http.server` handles the dashboard.

**Alternatives.**
- Node/TypeScript (matches openclaw, JS workspace) — rejected after the owner
  selected Python.
- Python with `httpx`/`fastapi`/`pyyaml` — rejected to keep zero-dependency;
  we hand-roll a tiny frontmatter parser and use `urllib`.

**Status.** Accepted (supersedes the initial Node/JS assumption).

---

## ADR-003 — Canonical message format = Anthropic content blocks

**Context.** Need a provider-agnostic internal representation for messages,
tool calls, and tool results.

**Decision.** Use Anthropic's content-block shape as the canonical format; the
OpenAI provider adapts to/from it.

**Rationale.** Anthropic is the default provider; tool_use/tool_result blocks
map cleanly and support streaming. One native path + one adapter is simpler
than a third neutral format.

**Alternatives.** A bespoke neutral schema — more code, more mapping, no gain
while Anthropic is the default.

**Status.** Accepted.

---

## ADR-004 — Skills use the `SKILL.md` (agentskills.io / hermes) standard

**Context.** Must reflect hermes' skills system and openclaw's skillsets, and
keep skills portable.

**Decision.** A skill is a directory with a `SKILL.md` (YAML frontmatter +
markdown body). Grounded on the *actual* installed hermes format
(`name`, `description`, `version`, `metadata.hermes.tags`, `When to Use`).
Discovery merges bundled + user dirs; user shadows bundled.

**Rationale.** Portability with the broader ecosystem; verified against the
real installed hermes skills rather than guessed.

**Alternatives.** A custom skill format — rejected; breaks portability.

**Status.** Accepted.

---

## ADR-005 — Progressive disclosure for skills and memory

**Context.** Injecting every skill/note into the prompt is wasteful and noisy.

**Decision.** The system prompt carries only a compact **index** (one line
each). The agent calls `load_skill` / `memory_get_note` / `memory_search` to
pull full content on demand.

**Rationale.** Keeps context small and cost low while scaling to many
skills/notes. Same pattern hermes uses.

**Status.** Accepted.

---

## ADR-006 — Memory is an Obsidian vault ("compile over retrieve")

**Context.** Owner instruction: keep the previous memory system; **using an
Obsidian vault for semantic memory is mandatory**.

**Decision.** Store memory as a directory of Obsidian-compatible markdown notes
with YAML frontmatter and `[[wikilinks]]`. Compile conversations/files into
notes (entities, classification, links) rather than embedding into a vector
store. Keyword search over the vault for v0.1.

**Rationale.** Matches the mandate and the "Compile over retrieve / Transparent"
principles. The vault is human-inspectable and editable in Obsidian. Stdlib
keyword search avoids an embeddings dependency.

**Alternatives.**
- Vector DB / embeddings — deferred to an optional upgrade (ADR-roadmap);
  conflicts with zero-dependency and "compile over retrieve."
- Single JSON memory file — insufficient for a semantic, linked, Obsidian
  vault; superseded.

**Status.** Accepted. Supersedes the initial JSON-file memory implementation.

---

## ADR-007 — Self-improvement is a scheduled nightly routine with an approval gate

**Context.** Owner definition of "self-improving": at **04:00 daily**, review
the last 24h of conversation and added files; improve the next day; author
skills; set up cron jobs; **get user approval before executing** consequential
actions.

**Decision.**
- A portable daemon (`birkin daemon`) wakes at `nightly_hour` (default 4) and
  runs `nightly.py`; it also runs due cron jobs.
- The nightly "night agent" **applies safe changes directly** (memory compile,
  skill authoring) but only **proposes** consequential actions (cron jobs,
  command execution) into a pending-approval queue.
- `birkin review` / the dashboard let the user approve/reject; only approved
  actions execute.

**Rationale.** Delivers autonomy while honoring "Transparent" and
"Human-in-the-loop." Separating *safe/auto* from *consequential/approved* keeps
trust without blocking useful self-improvement.

**Alternatives.**
- Fully autonomous execution — rejected; unsafe and against the explicit
  approval requirement.
- Approval for *everything* (incl. memory/skills) — rejected as too noisy;
  vault notes and skills are reversible and low-risk.

**Status.** Accepted.

---

## ADR-008 — Portable Python scheduler instead of OS cron

**Context.** Need scheduling on macOS/Linux/Windows without per-OS setup.

**Decision.** Implement scheduling as a long-running Python daemon loop. Offer
optional OS-native registration (`crontab`/`schtasks`) later as opt-in.

**Rationale.** One cross-platform implementation; no privileged setup required
to try it. Cron syntax differs across OSes and Windows has no native cron.

**Trade-off.** The daemon must be running to fire jobs; it does not survive
reboots by itself (mitigated by future opt-in OS registration).

**Status.** Accepted.

---

## ADR-009 — WebUI is a monitoring dashboard, not a chat client

**Context.** Owner clarification: the WebUI should show running jobs and result
summaries — it is a dashboard, not a chat.

**Decision.** The WebUI is read-mostly: status, scheduled/running jobs, recent
run summaries, and pending approvals (approve/reject). Chat stays in the CLI
REPL (`birkin chat`).

**Rationale.** Clear separation of concerns: terminal for interaction, browser
for observability and approvals. Smaller WebUI surface.

**Alternatives.** A 10-tab WebUI like the previous project — rejected as too
heavy for the lightweight goal.

**Status.** Accepted. Supersedes the initial streaming-chat WebUI prototype
(which is being reworked into the dashboard).

---

## ADR-011 — Add a lightweight gateway + onboarding (hermes-parity)

**Context.** Owner asked for an execution sequence identical to hermes: a
`setup` onboarding wizard and a `gateway`. The original non-goals (ADR-001)
excluded a multi-channel gateway.

**Decision.** Add a small **gateway control plane** (`birkin gateway`) with a
pluggable channel registry: a localhost **HTTP** channel by default and an
optional **Telegram** channel (stdlib long-polling). One shared session store
(memory + skills) backs every channel, with per-(channel, chat) history. Add a
guided **onboarding wizard** (`birkin setup`/`onboard`) that also runs on first
launch, plus `birkin tools` to enable/disable tools (hermes parity).

**Rationale.** Satisfies the explicit request while staying stdlib-only: HTTP
via `http.server`, Telegram via `urllib`. Channels are pluggable so more can be
added without touching the core. Revises ADR-001's gateway non-goal — but stays
far lighter than openclaw's 20+ channel gateway.

**Alternatives.** Full multi-platform gateway (Slack/Discord/WhatsApp/…) —
deferred; each is an opt-in channel module to add later.

**Status.** Accepted (partially supersedes the gateway non-goal in ADR-001).

---

## ADR-012 — Local CLI agents (Claude Code / Codex) as model backends

**Context.** Owner: birkin must run on the **installed `claude` (Claude Code)
and `codex` CLIs**, like hermes — using their own logins instead of an API key.

**Decision.** Add `claude-cli` and `codex-cli` providers. `models.discover`
detects the CLIs via `shutil.which` and lists them in the picker alongside API
and Ollama models. `LLMClient` shells out non-interactively
(`claude -p --output-format json [--model]`, `codex exec [-m]`), flattening the
conversation into the prompt and returning the reply as assistant text. No API
key needed (`get_api_key` returns a `"cli"` sentinel); birkin is a thin proxy
and does not run its own tool loop in this mode (the CLI agent runs its tools).

**Rationale.** Directly satisfies the requirement and reuses existing Claude
Code / Codex subscriptions. Stdlib-only (`subprocess`). Verified end-to-end:
`claude -p` returns `{"result": ...}` which birkin parses.

**Trade-off.** In CLI mode birkin's own tools aren't invoked as structured tool
calls. API providers remain the path for the native tool-calling loop.

**Update (ADR-014).** CLI mode is no longer a bare proxy: birkin now injects a
concise CLI system prompt with its **identity, memory digest, and the skills
routed to the request** (full text + bundled-script paths) so CLI agents answer
as birkin, use memory, and follow/execute skills with their own tools. See
ADR-014.

**Status.** Accepted.

---

## ADR-013 — Automatic skill-ization via nudges (copied from hermes)

**Context.** Owner: replicate hermes' automatic skill creation — the agent
"creates skills from experience" and "nudges itself to persist knowledge."

**Decision.** Copy hermes' nudge mechanism in the agent loop (no extra LLM
call): count tool-calling iterations; if a turn does substantial tool work
(`skill_nudge_interval`, default 3) without calling a skill tool, queue an
**ephemeral** note for the next turn suggesting `create_skill` / `improve_skill`.
A turn-based counter (`memory_nudge_interval`, default 6) does the same for
`remember` / `memory_write_note`. Counters reset when the relevant tool is used.
Nudges are added to the system prompt for one turn only and never stored in
history. Both intervals are configurable; `0` disables.

**Rationale.** Faithful to hermes (turn/iteration counters, ephemeral
injection, reset-on-use) and cheap — it steers the model to self-author skills
instead of running a separate reflection pass on every turn. The `/learn`
command and the nightly routine remain for explicit/batch consolidation; a
background "curator" (hermes' skill maintenance) is possible future work.

**Status.** Accepted.

---

## ADR-014 — Skills & memory work in CLI-agent mode via prompt injection

**Context.** Owner: hermes uses skills even on CLI agents — make birkin do the
same instead of treating CLI mode as a bare proxy (which also made the CLI act
like a translator, since no system prompt was sent).

**Decision.** For CLI providers, build a concise **CLI system prompt**
(`prompts.build_cli_system`) and send it with the conversation:
- birkin identity + "act, don't describe; answer in compact Markdown",
- a **memory digest** (`memory.render()`),
- the **skills routed to the request** (`SkillManager.route()` — keyword overlap
  on name/description/tags/body, top 3), rendered full-text via
  `render_skill()` including the skill's directory and bundled-script paths.

The CLI agent (Claude Code / Codex) then answers as birkin, uses the injected
memory, and follows/executes the skills with its own shell. The tool-oriented
guidance (`load_skill`, `spawn_subagent`) is omitted in CLI mode to avoid
confusion.

**Rationale.** Gives the hermes outcome (skills everywhere) without a
text-protocol tool loop over a completion backend. Routing keeps the prompt
small; bundled-script paths make skills executable in CLI mode too.

**Trade-off.** Skills are pre-selected by keyword routing rather than pulled on
demand; the CLI agent can't write back to birkin memory/skills within the turn
(captured later by `/learn` or the nightly routine).

**Status.** Accepted (refines ADR-012).

---

## ADR-015 — Per-turn run records + ledger + usage estimate (auditability)

**Context.** Improvement plan Phase 2 (idea from birkin_codex): make every turn
auditable.

**Decision.** Each chat/agent turn writes a JSON **run record** to
`~/.birkin/runs/` (provider, model, tools used, iterations, summary, usage) and
appends a compact line to `~/.birkin/ledger.jsonl`. `store.estimate_usage`
provides a transparent heuristic (chars/words/≈tokens = chars/4). Run ids carry
a short uuid suffix to avoid same-second collisions. `Session._record_turn`
captures this from `agent.last_tools` / `last_iterations`; `birkin runs` and the
dashboard surface it. `save_run` (also used by nightly/cron) now ledgers too.

**Rationale.** Cheap, dependency-free auditing + cost sense without a real
token API. Reuses the existing `store` + dashboard plumbing.

**Trade-off.** A file per turn accumulates in `runs/`; usage is an estimate, not
provider-reported. Pruning/retention can be added later.

**Status.** Accepted.

---

## ADR-016 — Config-driven local-cli runner + dry-run/packet mode

**Context.** Improvement plan Phase 3: reduce hardcoded provider dispatch and
add a cost-free way to inspect the prompt.

**Decision.** (a) Add a generic **`local-cli`** provider: `config.cli_command`
(argv) runs with the flattened prompt on stdin (via `proc.cli_argv`), stdout is
the reply — any local agent/model can be a backend without code. It joins the
existing providers; the native Anthropic tool-calling loop is unchanged and
remains the path for `anthropic`. (b) Add **`birkin chat --dry-run`** backed by
`runtime.build_dry_run_packet`, which assembles the exact system prompt + tool
names (or routed skills for CLI providers) + usage estimate **without a client
or API key**.

**Rationale.** Most of codex's config-driven-runner benefit (pluggable CLIs) and
its "packet" transparency, with minimal surface, no regression to the agentic
loop, and no new dependency.

**Trade-off.** Not a full multi-profile registry — a single active provider +
`cli_command`. A profiles map can be layered later.

**Status.** Accepted (extends ADR-003 / ADR-012).

---

## ADR-017 — Skill freshness: hot-reload, gating, sync, layered prompts

**Context.** Improvement plan Phase 4: keep the skill catalog fresh, scalable,
and context-appropriate (codex ideas: watch, eligibility, upstream mirror,
SOUL/AGENTS/TOOLS).

**Decision.**
- **Hot-reload**: `SkillManager.reload_if_changed()` compares a cheap mtime
  signature (stat only, debounced) and re-discovers on change; called before
  each turn so edited/added skills land without a restart.
- **Gating**: `Skill.eligible` checks frontmatter `prerequisites.commands`
  (via `shutil.which`) and `prerequisites.platforms`; `index()`/`route()` show
  only eligible skills, while `get()`/`load_skill` can still load by name.
- **Sync**: `birkin skills sync` (`skills/sync.py`) mirrors an upstream skill
  tree (auto-detected hermes, or `--from`) into `~/.birkin/skills/mirrors/`,
  preserving bundled scripts and appending a source-attribution line.
- **Layered prompts**: `prompts.workspace_prompt_block()` composes `SOUL.md` /
  `AGENTS.md` / `TOOLS.md` from the cwd into the system prompt when present.

**Rationale.** Matches codex's freshness/scale features with stdlib-only,
low-risk additions; gating prevents recommending skills that can't run here;
sync grows the catalog on demand without bloating the shipped package.

**Trade-off.** Hot-reload polls mtimes (no OS file-watch dependency); sync
mirrors verbatim (upstream license/attribution preserved, not transformed).

**Status.** Accepted.

---

## ADR-018 — Live-LLM verification harness (opt-in marker)

**Context.** Hardening Phase H2: the real agentic loop (Anthropic tool_use,
multi-turn, subagent) was only logic-verified by P1 fakes/monkeypatch — no
real-backend smoke in CI.

**Decision.** Add a `live` pytest marker; offline runs deselect it via
`addopts = "… -m 'not live'"`. Live tests skip themselves unless
`BIRKIN_LIVE=1` is set and a backend is available (`ANTHROPIC_API_KEY`, or the
`claude` / `codex` CLI on PATH). Cases:
- chat turn returns non-empty reply,
- chat-with-tool-or-useful-reply (asserts a tool was actually called when the
  native API loop is the backend; relaxed to "useful reply" for CLI proxies),
- subagent round-trip (skipped for CLI proxies, where no native subagent loop runs).
`scripts/smoke_live.{sh,ps1}` wraps the run.

**Rationale.** Closes the biggest v0.1 risk (unverified live paths) cheaply —
short prompts on Haiku-grade or CLI quota — without making offline CI
key-dependent. Easy to extend with more cases.

**Status.** Accepted.

---

## ADR-020 — Verified learning: Skill-PR mode + memory TTL

**Context.** Hardening Phase H4: the v0.1 review flagged two concrete risks —
(a) automatic skill writes had no audit trail (a paste of birkin_codex's
"+25 dealbreaker" complaint), and (b) "learned" avoidances were stored as
permanent skill text even when they were transient environment problems.

**Decision.**
- **Skill-PR mode.** `create_skill` and `improve_skill` no longer write the
  user-skills tree directly; they call `approvals.propose(category="skill", …)`
  with the full proposal payload. With the matching category in
  `auto_approve` (default) the proposal applies immediately; otherwise it
  queues in `pending/` and is applied by `birkin review`. Either way there is
  always a pending record. `manager.apply_skill_proposal(payload)` is the
  single writer; `improve_skill` forks bundled skills into the user dir
  instead of mutating them in place. Side effect: `auto_approve` default fixed
  from `["memory","skills"]` (the second was a no-op) to `["memory","skill"]`.
- **Memory TTL.** A note can declare an `expires_at` ISO date in frontmatter
  (`memory_write_note` exposes `ttl_days`). Expired notes are excluded from
  `list_notes`, `search`, and `render` (the prompt digest / router) so the
  agent stops seeing them. `get_note` still returns them by name for audit.

**Rationale.** Closes "no skill mutated without a recorded proposal" + "a
'learned' avoidance re-verifies before reuse" from the v0.1 review with the
minimum machinery. Reuses the existing approval/run-record audit plumbing —
no new subsystem.

**Trade-off.** Auto-approve keeps the agent fast by default (no friction in
the hot path); to require manual review, drop `skill` from `auto_approve`.
TTL is implemented as a hard filter (no gradual decay yet); negative-memory
typing arrives in H5.

**Status.** Accepted.

---

## ADR-019 — Reliability control plane: SIGTERM, stale heartbeat, budget, trace

**Context.** Hardening Phase H3: a hard kill could leave the dashboard
claiming a dead daemon was running, and there was no cost gate — silent failure
in either direction.

**Decision.**
- `scheduler.run_daemon` installs `atexit` and `SIGTERM` handlers that call
  `store.clear_status()`. `signal.signal` is wrapped in try/except for
  platforms / contexts where setting handlers isn't allowed.
- `store.is_status_stale(status, max_age_seconds=120)` decides whether a
  heartbeat is too old to trust; `/api/status` returns `stale` and forces
  `daemon: false` accordingly, so a crashed daemon never shows running.
- New `birkin/budget.py` sums `estTokens` from the run ledger over a window
  and reports / gates spending. `Session.ask` short-circuits over-budget turns
  with a clear message and writes a `skipped: over-budget` run record — no LLM
  call, no silent spend. `birkin budget` shows usage vs caps; dashboard surfaces
  the same. Defaults `0 = unlimited` so behavior is opt-in.
- `birkin trace <run-id>` prints a single run record (audit replay).

**Rationale.** Cheap, transparent reliability primitives — no daemon
supervisor, no metrics backend; just the heartbeat we already had + the run
ledger we already keep. Doesn't disturb the agentic loop or stdlib-only runtime.

**Trade-off.** Budget uses `estTokens` (chars / 4 heuristic), not exact
provider-reported cost; stale heartbeat is a fixed 120 s threshold; budget gate
is hard-stop (no soft warning yet). All adjustable in config / future ADRs.

**Status.** Accepted.

---

## ADR-028 — Rename the nightly routine to "Morpheus"

**Context.** The 04:00 self-improvement routine was named "nightly" — a
description, not a name. As the surface around it grew (CLI command,
slash command, run-record kind, config keys, status payload, dashboard
label, scheduler variables, install scripts, skill tags) the word
"nightly" got woven into 27 files. A descriptive name is fine for one
thing; for a *system* with its own role and personality (it watches the
day, writes memory, drafts skills, proposes automation — all while you
sleep) a proper name is clearer.

**Decision.** Rename the routine to **Morpheus** — the Greek god of
dreams. The canonical surface is now:

- module     ``birkin.morpheus`` (``birkin.nightly`` kept as a thin
                                  re-export shim)
- CLI        ``birkin morpheus`` (``birkin nightly`` is a hidden alias)
- slash      ``/morpheus``       (``/nightly`` is an alias)
- config     ``morpheus_hour`` / ``morpheus_minute``
             (``nightly_hour`` / ``nightly_minute`` migrated by
              ``load_config`` if only the old names are present)
- run record kind ``"morpheus"`` (the dashboard reads runs by kind; old
                                   ``"nightly"`` records remain visible)
- status JSON ``next_morpheus`` / ``morpheus_hour``
             (legacy ``next_nightly`` / ``nightly_hour`` emitted in
              parallel for any reader that still wants them)

**Rationale.** The cost of the rename is one commit; the benefit is a
proper noun the docs, README, and ASCII architecture diagram can hang on
("birkin → terminal → REPL → … → autonomy → Morpheus → approvals"). The
backwards-compat surface is small (a 12-line shim, two config-key
aliases, one status-payload duplicate) and easy to remove later.

**Trade-off.** External scripts that grep run-record kind for the
literal string ``"nightly"`` will miss new Morpheus runs. We mention
this in STATUS so callers update. Internal tests still pass via aliases.

**Status.** Accepted.

---

## ADR-027 — Shift+Enter via Kitty Keyboard Protocol (opt-in by terminal)

**Context.** ADR-026 shipped multi-line input bound to Ctrl-J / Alt+Enter.
Users asked for **Shift+Enter** (the chat-app convention) but the
standard TTY input stream does not preserve modifier-key information —
``Shift+Enter`` and ``Enter`` both arrive as bare ``\r`` on virtually
every conventional terminal (Terminal.app, iTerm2 default, default
Windows Terminal, VS Code integrated terminal).

A growing set of terminals (Kitty, WezTerm, Alacritty, foot, Ghostty)
implement the **Kitty Keyboard Protocol** (`CSI u`). In its
"disambiguate escape codes" mode (flag 1), modifier-bearing keys come
in as CSI sequences such as ``\x1b[13;2u`` (Shift+Enter),
``\x1b[13;5u`` (Ctrl+Enter), ``\x1b[13;3u`` (Alt+Enter); un-modified
keys (plain Enter, plain letters) still arrive unchanged. Terminals
that don't speak the protocol silently ignore the enable / disable
sequence — no negotiation, no fallback to manage.

**Decision.**
- Emit ``CSI > 1 u`` on REPL entry and ``CSI < u`` on exit. These are
  inert no-ops on non-supporting terminals.
- The POSIX raw reader recognises ``\x1b[13;<mod>u`` (any modifier
  value ≥ 2, single- or multi-digit) and emits the existing
  ``newline`` event — so Shift/Ctrl/Alt/Super+Enter all *just work* on
  Kitty-compatible terminals without any other code change.
- The legacy bindings (Ctrl-J, POSIX Alt+Enter = ``ESC + \r``) remain
  in place, so users on conventional terminals lose nothing.

**Rationale.** The choice is binary per terminal: either the protocol
is on (Shift+Enter natively) or it's off (Ctrl-J fallback). There is
no "Shift+Enter but only on some keypresses" failure mode to manage.
The regex (`^13;([2-9]|\d{2,})u$`) is futureproofed for protocol
modifier values ≥ 10 (combinations such as Shift+Alt+Ctrl+Super).

**Trade-off.** Users on terminals without CSI u still can't type
Shift+Enter as newline — there is no software-only fix. We document
Ctrl-J as the portable binding. The Windows ``msvcrt`` reader is not
wired into the protocol (Windows Terminal's CSI u support is still
inconsistent across builds); birkin keeps Ctrl-J / Alt+Enter as the
documented bindings there.

**Status.** Accepted.

---

## ADR-026 — Multi-line input

**Context.** ADR-023/024/025 incrementally built the line editor up to
"5000-character single-line input never breaks layout." Users still
could not type a multi-line prompt (e.g. paste a code block, write a
spec body across paragraphs). Enter both submitted *and* wrapped on
some terminals, ambiguously. ADR-025 paste batching even stripped
``\n`` from pasted content because the read loop classified newline as
"control".

**Decision.**
- Split the two semantic roles cleanly: ``\r`` = **submit**, ``\n`` =
  **newline**. POSIX maps Ctrl-J directly to ``\n``; Windows
  ``msvcrt.getwch`` returns ``\n`` for Ctrl-J as well. Additionally
  POSIX detects ``ESC + \r`` / ``ESC + \n`` as Alt+Enter and treats it
  as the newline trigger — that's the binding most users muscle-memory
  to from chat clients and editors.
- Paste batching is updated to preserve ``\n`` and ``\t`` in the
  batched ``("char", text)`` event; only ``\r`` and other control
  bytes abort the batch (and are pushed back to be handled normally).
  So a multi-line paste arrives in one event and lands in the buffer
  verbatim.
- The state machine learns a ``newline`` event that inserts a literal
  ``\n`` at the cursor (parallel to ``char`` but explicit).
- ↑/↓ become **line navigation** when the buffer contains ``\n``;
  history navigation is reserved for single-line input so a half-typed
  multi-line draft can never be lost to an accidental ↑. The dropdown
  still wins precedence when active (it depends on the first token
  being whitespace-free, so dropdown ⟂ multi-line in practice).
  Column is preserved across line jumps, clamped to the destination
  line's length.
- ``_redraw`` splits the buffer on ``\n``, draws each logical line as
  its own screen row (first row carries the prompt; subsequent rows
  get a prompt-width indent), and applies the existing horizontal-scroll
  rule per row. The dropdown lands below the last input row, and the
  cursor is parked at its logical ``(row, col)`` via
  ``cursor_row_col``. The redraw now returns
  ``(cursor_row, total_rows)`` so the next frame walks back up to the
  anchor and overwrites cleanly even when the input grew/shrank rows.

**Rationale.** This is the simplest decomposition that gives a real
editor experience without re-architecting the loop or pulling in a
TUI library. Every new behavior is a pure transition (testable) plus
one redraw change.

**Trade-off.** No incremental history search (Ctrl-R) yet, no
word-jump (Alt-B/F), no bracketed-paste protocol detection (we rely on
the OS-level batch arrival to identify a paste). All extensions to the
same state machine.

**Status.** Accepted.

---

## ADR-025 — Long-input handling: paste batching + horizontal scroll

**Context.** ADR-023/024 shipped the inline dropdown and line editor, but
two problems surfaced for long inputs:
1. A single paste of N characters generated N raw-input events and N
   redraws — for 5000 characters this flickered visibly and felt slow,
   even though the buffer (a Python ``str``) had no real size limit.
2. When the input grew past the terminal width, ``\x1b[2K`` only cleared
   the current row, so the wrapped portion stayed on screen and the
   redraw rewrote on top of it — visible corruption.

**Decision.**
- **Paste batching.** ``_read_event_posix`` and ``_read_event_windows``
  now coalesce consecutive printable / UTF-8 bytes into a single
  ``("char", text)`` event. On POSIX, after the first printable byte we
  ``select.select(…, timeout=0)`` and drain whatever the OS has buffered;
  the moment we see a control byte (``< 0x20``, ``0x7f``, or ``0x1b``)
  we push it onto a module-level pushback list and stop the batch so the
  next call sees the control byte intact. On Windows ``msvcrt.kbhit()``
  drives the same loop, with ``msvcrt.ungetwch`` providing native
  pushback.
- **Horizontal scrolling.** A new pure helper
  ``compute_view(buffer_len, cursor, content_width)`` returns a
  ``(view_start, view_end)`` window large enough to fit the cursor; the
  heuristic places the cursor ~70 % into the window so the next typed
  character isn't immediately at the right edge. ``_redraw`` calls
  ``shutil.get_terminal_size`` per redraw, computes the window, writes
  ``…`` markers on clipped sides, and positions the cursor at the
  visible offset.

**Rationale.** Both fixes are local — one to the read functions, one to
the redraw — and both have pure helpers we can unit-test offline.
Together they make the buffer effectively unbounded for human use:
5000-character pastes redraw once, and the terminal layout never breaks
no matter how long the buffer grows.

**Trade-off.** ``compute_view`` is stateless (no memory of the previous
window), so the visible window can jump when the cursor moves far in one
step — fine for paste and arrow navigation, slightly noisier than a
sticky-window line editor. Multi-line input and bracketed-paste
detection are still deferred (see ADR-024).

**Status.** Accepted.

---

## ADR-024 — Line editor: cursor motion, Delete, persistent history

**Context.** ADR-023 shipped the inline `/cmd` dropdown but left first-rev
gaps: no left/right cursor motion inside the buffer, no Home/End, no
Delete-under-cursor, no ↑/↓ command history. Hermes' README advertises a
real REPL line editor; closing the gap also makes day-to-day correction
of typos tractable for users.

**Decision.**
- Refactor the I/O loop around a pure state machine: `EditorState`
  (buffer + cursor + selection + history pointer) and
  `apply_event(state, event, commands, history)`. Every user-visible
  behavior except actual key reading and screen redraw is now a pure
  transition, so the bulk of the logic is covered by offline tests.
- Add cursor motion keys: ←/→, Home/End, plus Ctrl-A / Ctrl-E (POSIX) and
  the Windows extended-key codes (`G/O/K/M`). Typing inserts at the
  cursor; **Delete** removes the character *under* the cursor while
  **Backspace** removes the character *before* it (the standard line-editor
  semantics — not what readline-less environments default to).
- POSIX raw mode reads the ESC byte and then drains a CSI / SS3 sequence
  via `select.select` with a ~30 ms timeout to distinguish bare Esc from
  navigation keys. Supports `[A/B/C/D`, `[H/F`, `[1~/4~/7~/8~`, `[3~`.
- ↑/↓ navigates the in-memory history list when the dropdown is inactive;
  the history list is loaded from and persisted to
  `~/.birkin/sessions/repl_history.txt` (one line per submitted command,
  blanks and consecutive duplicates skipped, default cap 500). The first
  Esc while browsing history restores the line the user had been drafting
  before they started navigating.

**Rationale.** A persistent, navigable history is the smallest single
addition that moves the REPL from "you can type slashes now" to "this feels
like a real shell." Putting transitions in `apply_event` made adding the
six new key kinds (left, right, home, end, delete, history-up/down) a
matter of cases in one function, with the test surface scaling linearly.

**Trade-off.** No word-jump (Alt-B/F / Ctrl-←/→) yet, no incremental
history search (Ctrl-R), no multi-line input, no paste-as-bracketed-paste
detection. All are extensions to the same state machine and can ship
without re-architecting.

**Status.** Accepted.

---

## ADR-023 — Inline slash-command autocomplete (stdlib only)

**Context.** A sourced comparison against hermes-agent and openclaw
(`docs/COMPARISON.md`) revealed that "slash-command autocomplete" had been
described as a copied UX element from hermes but was not actually wired into
the REPL — `repl.py` used a plain `input()` and the user had to memorize or
`/help` to discover commands. The hermes README explicitly advertises
slash-command autocomplete; openclaw does not, and Claude Code itself uses
an inline-dropdown pattern.

**Decision.** Implement an inline dropdown in `birkin/inline_complete.py`,
stdlib only, that activates when the buffer starts with `/`. Behavior:
- ↑/↓ moves selection within the filtered match list.
- **Tab** behaves as completion: when there's a unique match (or the user
  navigated explicitly) it commits the command with a trailing space;
  otherwise it extends the buffer to the longest common prefix.
- **Enter** submits the current buffer as typed (no implicit completion).
- **Esc** dismisses the dropdown but keeps the buffer.
- Cross-platform raw key reading: POSIX termios (with UTF-8 multi-byte
  reassembly via leading-byte inspection) and Windows `msvcrt.getwch`
  (which already returns wide characters).
- On non-TTY stdin/stdout the function falls back to plain `input()`.

Matching, ranking, and rendering are exported as pure functions
(`filter_commands`, `common_prefix`, `render_menu_lines`) — the I/O loop
is the only side-effecting part — so the bulk of the logic is unit-tested
offline (20 cases in `test_inline_complete.py`).

**Rationale.** Closes a real promise/implementation gap the comparison
surfaced. Costs no runtime dependency (the rest of the codebase is also
stdlib only). The non-TTY fallback keeps the existing test harness and
`harness-runner` automation working unchanged.

**Trade-off.** First-revision minimalism: no left/right cursor motion
inside the buffer (typing happens at the end of the line); no command
history yet (the previous `readline` import remains but is bypassed). Both
are deliberate — the next revision can extend the same module instead of
re-writing it.

**Status.** Accepted.

---

## ADR-022 — Skill integrity (`skills validate`) + risk-tiered approval inbox

**Context.** Hardening Phase H6 closes the trust gap on two specific
failure modes:
1. A broken or malformed `SKILL.md` (missing frontmatter, syntactically broken
   bundled Python script) could ship in the catalog and only blow up when the
   agent finally tries to use it — at the worst moment, mid-task.
2. The approval inbox was a flat list — a low-risk memory write looked
   identical to a high-risk shell execution, so a tired human could
   rubber-stamp the wrong line.

**Decision.**
- `birkin/skills/validate.py` validates every `SKILL.md` in
  bundled + user + extra dirs. Required fields (`name`, `description`) are
  **errors**; recommended (`version`, `license`) and a `## When to Use`
  section are **warnings**. Every Python file shipped *inside* a skill
  directory is run through `py_compile.compile(..., doraise=True)`; a syntax
  error is reported with the offending file's name and an exit-non-zero
  status. Surfaced as `birkin skills validate` (with `--verbose` for
  warning-only skills); zero new dependencies.
- `birkin/risk.py` maps each approval category to a tier
  (`memory`/`skill` = low, `cron` = medium, `shell` = high) and provides
  `sort_by_risk` + a one-glyph `label`. Unknown categories default to
  `medium` — fail-safe. `approvals.review_cli` and `/api/approvals` order
  pending items highest-risk-first and tag each line with its tier.
- Risk tagging is **strictly display**: auto-approval is still governed by
  `config["auto_approve"]`. We deliberately did *not* couple the two so
  changing one never silently changes the other.

**Rationale.** Both checks are pure-stdlib, run in milliseconds, and target
the failure modes we'd otherwise discover at the worst time (broken script
mid-run; rubber-stamped shell command). They also give the GUI/dashboard
something useful to render later without backfilling state.

**Trade-off.** `skills validate` is intentionally narrow — it does NOT
sandbox or *execute* bundled scripts; `py_compile` catches syntax-level
breakage, not runtime bugs. Risk tiers are a small static table — they don't
look at the *content* of a proposal (e.g. an `rm -rf /` shell command is
still just "high", same as `ls`). Both are documented escape hatches for
future work (skill signing, payload-aware risk scoring).

**Status.** Accepted.

---

## ADR-021 — Memory OS: polarity, version (optimistic lock), evidence gate

**Context.** Hardening Phase H5. The vault was already a literate semantic
memory, but had three blind spots:
1. There was no way to mark a note as *what NOT to do* — past failures looked
   the same as past wins, so the agent could happily re-run a known-bad pattern.
2. Two writes to the same note silently last-write-wins; a refining write off a
   stale snapshot could clobber a more recent one.
3. Anyone (the agent, a tool, a script) could write a note with no source at
   all, leaving the vault full of low-confidence claims with nowhere to look up
   their provenance.

**Decision.**
- **Polarity** — every note carries `polarity: positive | negative` in
  frontmatter (default `positive`). The render digest (which seeds the system
  prompt) annotates negative notes with `⚠ known failure — re-verify`, so
  failure memories surface *in the prompt* rather than being indistinguishable
  from successes. `memory_write_note` exposes a `polarity` field; subsequent
  writes inherit the existing polarity unless explicitly overridden; invalid
  polarities raise.
- **Version (optimistic lock)** — every note carries `version: N` (starts at 1,
  bumped on every write). Callers may pass `expected_version` to refuse stale
  overwrites: `write_note` raises `VersionMismatchError`; the
  `memory_write_note` tool catches it and returns a friendly `is_error` so the
  agent can re-read and retry instead of crashing.
- **Evidence gate (opt-in)** — `evidence_required: true` in config refuses any
  *new* note without at least one `source`. Defaults to off to keep existing
  helpers (tests, `improve_skill`, ad-hoc internal writes) working unchanged;
  users who want a strict-provenance vault flip the switch.

**Rationale.** All three concerns share the same shape: a note is a small
versioned, attributed claim. Polarity is one extra bit of frontmatter; version
is one integer; evidence is a single non-empty check. No new tables, no
embeddings, no schema migration — just three more lines in the YAML header,
parsed by the same `frontmatter.parse` we already use.

**Trade-off.** `expected_version` is opt-in per call site — if a caller never
sets it, last-write-wins still applies (the version still increments, but no
mismatch is detected). The evidence gate is opt-in for backwards-compat. Both
are deliberate: the goal is to *enable* discipline, not impose it everywhere
the moment the flag exists.

**Status.** Accepted.

---

## ADR-010 — Single shared session, sequential dashboard server

**Context.** Local, single-user tool.

**Decision.** Use a plain (sequential) `HTTPServer` with one shared `Session`,
guarded by a lock. No async framework.

**Rationale.** A single local user does not need concurrency; sequential
handling avoids races on the shared agent/session and keeps the code tiny.

**Status.** Accepted.
