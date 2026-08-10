---
name: morpheus
description: "Nightly unattended self-improvement — review the last 24h, compile memory + skills (auto-applied), and PROPOSE consequential actions for approval. Never destructive."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [automation, self-improvement, memory, nightly, unattended]
entrypoint: "birkin morpheus  ·  birkin daemon --install (cron/launchd/schtasks @ morpheus_hour, default 07:00)"
    legacy_alias: nightly
---

# Morpheus — nightly self-improvement

While the user sleeps, birkin reviews the last 24 hours of conversation and
changed files, then improves tomorrow: it compiles the Obsidian memory vault and
authors/refines skills (both **auto-applied**, because they are reversible local
files), and **proposes** convenience actions and cron jobs (**queued for
approval**, never executed in the run). Named after the Greek god of dreams; the
obsessive-clarity sibling is the `neurosis` skill.

**Runs UNATTENDED, so be concrete, conservative, and never destructive.** No one
is awake to confirm anything; anything outside the allow-list is denied, not
deferred to a human.

## When to Use

- Triggered automatically each day at `morpheus_hour` (default 07:00) by the
  installed daemon (`birkin daemon --install`).
- On demand: `birkin morpheus` (full pass) or `birkin morpheus --dry-run`
  (analyze only — write nothing, propose nothing).
- The legacy name `nightly` (module / CLI / slash / run record / config key) is
  preserved as an alias.

## When NOT to Use

- For anything the user is waiting on right now — Morpheus is a background pass,
  not an interactive turn.
- To take consequential action directly — Morpheus only *proposes* those; the
  user approves later with `birkin review`.
- When there is nothing new (no saved conversations / no changed files in 24h) —
  produce a short "nothing to learn today" summary and stop.

## Inputs (assembled by the routine, then handed to you)

1. **Conversations — last 24h.** Auto-saved transcripts from `~/.birkin/sessions/`
   (`auto__*.json`, the secret-redacted turn pairs the gateway/REPL persist),
   rendered to text and capped (~20k chars).
2. **Changed files — last 24h.** A walk of the working directory by mtime,
   excluding `.git`, `.birkin`, `node_modules`, `__pycache__`, `.venv`, `dist`,
   `build`, etc. (up to ~60 paths).
3. **Recent activity log** (`~/.birkin/ledger`-backed activity, capped ~6k chars).

## Procedure

Do all that apply, in this order, using the birkin tools provided over MCP
(`mcp__birkin__memory_write_note`, `…create_skill`, `…improve_skill`,
`…propose_action`, plus `…memory_search` / `…memory_get_note` / `…memory_link`).
Analyze the workspace with **Read / Glob / Grep only** — there is **no shell**.

### 1. Memory (auto-applied)

Capture durable **entities, facts, decisions, and relationships** in the Obsidian
vault with `memory_write_note`, linking related notes with `[[wikilinks]]`.
**Update existing notes rather than duplicating** (search first with
`memory_search` / read with `memory_get_note`). Prefer sourced facts; respect
`evidence_required` when set. Skip transient chatter — only what helps tomorrow.

### 2. Skills (auto-applied)

If you observed a **repeatable procedure**, `create_skill` (or `improve_skill` an
existing one). Keep them **generalizable** and hermes/agentskills-compatible
(frontmatter: `name`, `description`, `version`, `license`; a clear "When to Use").
Skill writes are validated (frontmatter lint + `py_compile` for any scripts).

### 3. Proposals (queued for approval — NOT executed)

For anything that would help tomorrow but **changes the world** (scheduled
digests, prefetching, reminders, automations), call `propose_action`. These are
**queued**, never run during the pass. Use:

- `category: "cron"` with `payload: {name, hour, minute, type: "prompt"|"shell", value}`
- `category: "shell"` with `payload: {command}`

Do **not** propose risky or destructive actions. A `cron` whose `type` is `shell`
cannot bypass the `shell` approval gate — if `shell` is not also approved, it
stays queued.

### 4. Summary

Finish with a short **plain-text** summary, prefixed with the label
**`[Morpheus]`**: what you **learned**, what you **saved** (memory/skills), and
what you are **proposing**. This becomes the run record (`birkin runs` /
`birkin trace <id>`).

## Security model (why this is safe to run unattended)

- **Free + sandboxed path** (provider `claude-cli`): a Claude Code run launched
  with `--allowedTools` = `Read, Glob, Grep` **+ `mcp__birkin__*`** only, plus
  `--strict-mcp-config` and `permission_mode: "default"`. No Bash, no arbitrary
  file writes — anything outside the allow-list needs an approval no one is there
  to give, so it is denied (defence-in-depth around the allow-list).
- **API-key path** (own agent loop): the tool registry is restricted to
  `{files, web, skills, memory}` + `propose_action` — **no direct shell or
  subagent**. Consequential actions go only through `propose_action` →
  the `approvals` queue.
- In **both** paths, memory + skills are auto-applied (reversible), while
  cron/shell are queued and risk-tiered for `birkin review`.

## Output

- Memory notes written/updated in `~/.birkin/vault/` (with `[[wikilinks]]`).
- New/refined skills under `~/.birkin/skills/`.
- Convenience actions / cron jobs **queued** in `~/.birkin/pending/`
  (approve/reject with `birkin review`).
- A run record (`store.save_run("morpheus", …)`) — inspect with `birkin runs`,
  replay with `birkin trace <run-id>`.

## Notes

- `--dry-run` analyzes and reports only: it writes no memory/skills and proposes
  nothing. Use it to preview tonight's pass with zero side effects and zero cost.
- Conservative beats clever: a missed note is recoverable next night; a wrong
  auto-applied change erodes trust. When unsure whether something is durable,
  prefer a proposal over a silent write.
- Pairs with the auto-save pipeline (the gateway/REPL persist redacted turn
  pairs) and `neurosis` (whose approved specs can be saved to memory for Morpheus
  to act on later).
