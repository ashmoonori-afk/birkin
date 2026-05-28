# birkin vs hermes-agent vs openclaw — Sourced comparison

> Snapshot: 2026-05-28. Goal: fact-grounded reality check. Anything I could not
> verify from a primary source is marked **(unverified)** and excluded from
> the verdict.

## Sources

- **hermes-agent** — `https://github.com/NousResearch/hermes-agent` (README,
  AGENTS.md). License: MIT.
- **openclaw** — `https://github.com/openclaw/openclaw` (README) and
  `https://docs.openclaw.ai/tools/skills`. License: MIT.
- **birkin** — this repo (`docs/STATUS.md`, `docs/DECISIONS.md`, the actual
  source under `birkin/`, `pytest --cov` output 2026-05-28).

## Feature matrix

| Dimension | hermes-agent | openclaw | birkin |
|---|---|---|---|
| **Runtime / stack** | Python 88.9% + TypeScript 8.3%; Python 3.11, Node.js, ripgrep, ffmpeg (README) | Node 24 recommended (Node 22.19+); pnpm/npm/bun (README) | Python 3.10+, **stdlib only** runtime (`pyproject.toml` `dependencies = []`) |
| **License** | MIT (README) | MIT (README) | Dual: `birkin/` Python package Proprietary; `skills/` MIT (`LICENSE`) |
| **Skill format** | `name/description/version/author/license/platforms` + sections (When to Use, Prerequisites, How to Run, Quick Reference, Procedure, Pitfalls, Verification) (AGENTS.md) | `name`, `description` minimal; metadata single-line JSON; `requires.bins / anyBins / env / config`, `os`, `primaryEnv` gating (docs/tools/skills) | hermes-compatible frontmatter; parser also handles `metadata.hermes.tags`; bundled catalog: **48 skills** verified clean by `skills validate` |
| **Skills registry** | "compatible with the agentskills.io open standard" (README) — no first-party large registry described | **ClawHub** registry; community-curated ~5,400+ via `VoltAgent/awesome-openclaw-skills` (README + that list) | 48 bundled + runtime `skills sync` from upstream into `~/.birkin/skills/mirrors/` |
| **Skill validation** | "No formal validation or linting pipeline is described" (AGENTS.md) | "The documentation does not mention a `skills validate` command" (docs check) | **`birkin skills validate`** — frontmatter lint (errors on missing `name`/`description`; warns on `version`/`license`/`When to Use`) + `py_compile` on every bundled `*.py`. 48/48 clean on the shipped catalog. |
| **Memory architecture** | FTS5 session search + LLM summarization + Honcho dialectic user modeling; plugin providers (honcho, mem0, supermemory, byterover, hindsight, holographic, openviking, retaindb) (AGENTS.md) | Not detailed in README; `sessions_list/history/send/spawn` tools | **Obsidian vault** (markdown + `[[wikilinks]]` + frontmatter); polarity (positive/negative), version (optimistic lock), TTL via `expires_at`, opt-in evidence gate (ADR-021, `tests/test_memory_os.py`) |
| **Memory provider plugins** | 8 documented (above) | Not documented | 1 (vault) — intentional; embeddings deferred |
| **Self-improvement loop** | Curator system; configurable `curator.interval_hours` (AGENTS.md) | Not detailed | Nightly **04:00** routine with restricted toolset; routes all writes through approvals (`nightly.py`, ADR) |
| **Gateway / channels** | Telegram, Discord, Slack, WhatsApp, Signal, CLI (README) — 6 | WhatsApp, Telegram, Slack, Discord, Google Chat, Signal, iMessage, IRC, Teams, Matrix, Feishu, LINE, Mattermost, Nextcloud Talk, Nostr, Synology Chat, Tlon, Twitch, Zalo, Zalo Personal, WeChat, QQ, WebChat (README) — 23 | HTTP + Telegram (optional) — **2** |
| **Terminal / execution backends** | local, Docker, SSH, Singularity, Modal, Daytona (README) — 6 | host main session + sandbox for non-main; bash/process/read/write/edit (README) | local only via `proc.py` (argv-only, no `shell=True`) |
| **Voice / multimodal** | "Voice memo transcription" (README) | "Voice Wake + Talk Mode", "Live Canvas" with A2UI (README) | None |
| **Model picker (incl. local CLIs)** | `hermes model` switches across Nous Portal / OpenRouter / NovitaAI / NIM / HF / OpenAI / custom endpoint (README) | Per-agent skill/model routing via `openclaw.json` | `birkin model` shows API + claude-cli/codex-cli/local-cli; `provider="local-cli"` runs any argv with prompt on stdin |
| **Slash commands** | "slash-command autocomplete" (README) — exact list not enumerated | `/status /new /reset /compact /think /verbose /trace /usage /restart /activation` (README) | 29 registry-based slash commands (`birkin/slashcommands.py`) |
| **Onboarding wizard** | `hermes setup` with prior-config detection + migration (README) | "OpenClaw Onboard" steps through gateway/workspace/channels/skills (README) | Arrow-key onboarding wizard + first-run auto-trigger (`onboarding.py`) |
| **Approval gate / human-in-the-loop** | "Command approval" + gateway message guards mentioned; "no approval-gate workflow for skills themselves" (AGENTS.md) | DM policies (`pairing` default, `open` for public); sandbox modes; `openclaw doctor` surfaces risky configs (README) | Explicit propose/approve gate with `auto_approve` per category; **Skill-PR mode**: `create_skill`/`improve_skill` always route through the gate (ADR-020) |
| **Risk tiers on approvals** | "No risk tiers are defined" (AGENTS.md) | "no per-skill permission model or signature verification is documented" (docs check) | `birkin/risk.py`: memory/skill=low, cron=medium, shell=high; unknown→medium (fail-safe). `review` + `/api/approvals` order by risk (ADR-022) |
| **Skill signing / immutable official** | Not described | Path-based containment (realpath inside configured root); third-party skills "treat as untrusted code" (docs) | Bundled skills never edited in place — `improve_skill` forks into user dir (ADR-020) |
| **Reliability primitives** | Not enumerated in README | `openclaw doctor` for misconfig | SIGTERM/atexit clear status; stale-heartbeat (>120s) ⇒ stopped; **budget governor** (`estTokens` ledger window, daily/monthly cap, hard-stop with skip record); `birkin trace <run-id>` audit replay (ADR-019) |
| **Test suite (sourced)** | "~17k tests across ~900 files" (AGENTS.md); coverage not stated | Not mentioned in README | **199 tests**, **coverage 79.95%** (`pytest --cov`, 2026-05-28); offline + no API key required |
| **Live-LLM verification harness** | Not described | Not described | `@pytest.mark.live` marker, opt-in via `BIRKIN_LIVE=1`; `scripts/smoke_live.{sh,ps1}` (ADR-018) |
| **Auditability** | Not enumerated in README | `sessions_history` tool | Per-turn run records + append-only `ledger.jsonl` with `estTokens`; `birkin runs` / `birkin trace` (ADR-015) |
| **WebUI** | Not described in README | "Live Canvas" + A2UI (README) | Monitoring dashboard at `/api/{status,jobs,runs,approvals,skills}` (no chat) |

## Honest verdict

### Where birkin loses against hermes (at scale)
- **Test count**: 17k vs 199 (orders of magnitude). Coverage % isn't comparable
  because hermes doesn't publish one, but the raw surface area is far smaller
  on birkin.
- **Memory plugin variety**: 8 documented providers (honcho, mem0, etc.) vs 1
  vault. birkin deliberately picked one substrate and went deep on its
  semantics; hermes went wide.
- **Execution backends**: hermes ships Docker/SSH/Modal/Daytona/Singularity;
  birkin is local-only.
- **Voice / multimodal**: hermes does voice memo transcription; birkin none.

### Where birkin loses against openclaw (at scale)
- **Channels**: openclaw 23, birkin 2.
- **Skills registry**: ClawHub ecosystem with ~5,400+ community skills; birkin
  has 48 bundled + runtime mirror.
- **Voice / canvas**: Voice Wake + Talk Mode + Live Canvas; birkin none.

### Where birkin wins (only counting things explicitly absent from the upstream sources I read)
- **`skills validate` with `py_compile`**: not in hermes AGENTS.md, not in
  openclaw skills docs.
- **Explicit risk tiers** on the approval inbox: hermes AGENTS.md says "No
  risk tiers are defined"; openclaw docs have no per-skill permission model.
- **Polarity + optimistic-lock memory**: not in either upstream's documented
  memory layer.
- **Token budget governor** + ledgered `estTokens` + `birkin trace`:
  not surfaced in either README.
- **Stdlib-only runtime**: hermes pulls in Node + ripgrep + ffmpeg as host
  prereqs; openclaw is a Node ecosystem. birkin's `dependencies = []` is a
  real cross-platform install advantage at the cost of feature reach.
- **Coverage-gated CI**: birkin enforces ≥75% via `fail_under`; hermes/openclaw
  don't surface this in the docs I read.

### Comparable / tied
- **Skill format** — birkin parser handles hermes' `metadata.hermes.tags`, so
  catalogs are mutually portable (`skills sync` is built on this).
- **Slash commands** — all three have rich command sets; birkin's 29 vs
  openclaw's 11 named (hermes doesn't enumerate).
- **Onboarding wizards** — all three ship one.
- **CLI-agent-as-backend** — birkin's `local-cli` provider matches the spirit
  of hermes' "any model you want" matrix.

### One-line positioning

> **hermes** = breadth of providers and execution surfaces; **openclaw** =
> breadth of channels and community skills; **birkin** = depth on
> trust/safety/reliability (validation, risk tiers, polarity-aware memory,
> budget, audit) on a stdlib-only Python core.

## Strategic implications

1. **Don't chase breadth.** The matrix above is unambiguous — hermes and
   openclaw will out-feature birkin on channels/providers/backends for the
   foreseeable future. Trying to match them is a losing race.
2. **Lean into the trust gap.** Validation, risk tiers, polarity memory,
   budget, and ledgered audit are the differentiators. Make them more
   *visible* (dashboard cards, CI badges, an HTML diff for skill PRs).
3. **One channel chosen deliberately beats N**. GTM track says LINE first —
   that's still right. Pick one Asian channel openclaw didn't polish for
   business use, do it with the full audit story.
4. **Honesty in marketing.** README must say "smaller and more careful, not
   bigger and faster" — claiming parity with hermes/openclaw on breadth
   would be falsifiable.

## Caveats / what I did NOT verify

- I read each upstream's **README + AGENTS.md / skills docs**, not the full
  source. Any feature these projects ship but don't document in those pages
  is *invisible* to this comparison.
- hermes' "~17k tests" is sourced to AGENTS.md but I didn't run them; coverage
  is not stated in either upstream.
- openclaw's skill count (5,400+) is via `VoltAgent/awesome-openclaw-skills`,
  not openclaw's own README — treat as ballpark.
- Memory mechanism in openclaw might exist but is undocumented in the README
  I read; the "Not detailed" cells reflect *my* visibility, not absence.
