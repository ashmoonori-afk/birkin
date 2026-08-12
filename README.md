<div align="center">

```
 ██████╗ ██╗██████╗ ██╗  ██╗██╗███╗   ██╗
 ██╔══██╗██║██╔══██╗██║ ██╔╝██║████╗  ██║
 ██████╔╝██║██████╔╝█████╔╝ ██║██╔██╗ ██║
 ██╔══██╗██║██╔══██╗██╔═██╗ ██║██║╚██╗██║
 ██████╔╝██║██║  ██║██║  ██╗██║██║ ╚████║
 ╚═════╝ ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝
```

### The agent whose memory cannot delete itself.

🌐 **Language**: English · [한국어](./README.ko.md)

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-6fe7ff?style=flat-square&labelColor=070b12)](./pyproject.toml)
[![Runtime dependencies: 0](https://img.shields.io/badge/runtime_dependencies-0-b8f36b?style=flat-square&labelColor=070b12)](./pyproject.toml)
[![Tests](https://img.shields.io/github/actions/workflow/status/ashmoonori-afk/birkin/tests.yml?branch=main&style=flat-square&label=tests&labelColor=070b12)](https://github.com/ashmoonori-afk/birkin/actions/workflows/tests.yml)
[![MIT](https://img.shields.io/badge/license-MIT-ffbd66?style=flat-square&labelColor=070b12)](./LICENSE)

</div>

![A deterministic execution graph crossing a lexical memory lattice](./docs/assets/birkin-graph-engineering.png)

> **Memory is files. Control flow is code. Authority is bounded.**

birkin is a personal agent for Claude and Codex, in your terminal and on
Telegram. Three decisions separate it from a prompt loop wearing an
orchestration costume.

**Memory is a folder you own.** Obsidian-compatible Markdown under
`~/.birkin/vault`. Open it, grep it, diff it, commit it. It outlives the
runtime that wrote it.

**Multi-agent work is a Python graph.** Not a model deciding to call itself.
Roles bind to providers before anything spawns, and the ceilings are checked in
code on the way into every spawn.

**The curator cannot delete.** Not "is instructed not to". The plan type admits
exactly five operations, `rezone`, `link`, `supersede`, `archive`, and
`annotate`, and a deterministic executor decides what actually lands. There is
no delete for an adversarial model, a poisoned note, or a bad night to reach
for. Check it rather than trust it: [the contract](./birkin/curation_contract.py),
[the executor](./birkin/curation_apply.py).

---

## The 60-second proof

Every row below is a number the repository can be made to produce.

| | Measured or enforced |
|---|---|
| **0 runtime dependencies** | The shipped package is stdlib only: [`dependencies = []`](./pyproject.toml). |
| **5 curation operations, none of them delete** | [`OPS`](./birkin/curation_contract.py) is the whole vocabulary a curator gets. |
| **R@1 0.891 in production** | The shipped lexical stack scores 0.891 R@1 and 0.974 R@5 on 470 LongMemEval-S questions. The tuned research stack reaches 0.900, ahead of the best embedding hybrid measured on the same harness. [Reproduce it](./benchmarks). |
| **9.1x cheaper context** | Top-5 retrieval against long-context, and 371x against loading a 1,910-note vault wholesale. [Raw token counts](./benchmarks/results/tokencost-20260712-0737.json), [method and the negatives](./docs/ranking-v2-plan.md). |
| **4 concurrent execution slots, 100-agent ceiling** | Moirai's default thread-pool width and per-run spawn cap. These are scheduling limits, not the six named workers further down. Abort, token budget, and spawn cap are all evaluated before a new agent starts. [Engine source](./birkin/moirai/engine.py). |
| **Every call journaled before return** | Provider, model, phase, status, tokens, traceback, and resume key land in SQLite while the run is still going. [Journal source](./birkin/moirai/journal.py). |

<details>
<summary><strong>Or skip this README and make your agent audit the claims</strong></summary>

```text
Read this README and the implementation files it links to. Tell me whether
birkin is graph engineering or a prompt loop, which actions a model can never
authorize for itself, and where the project publishes benchmark results that
went against it:
https://raw.githubusercontent.com/ashmoonori-afk/birkin/main/README.md
```

</details>

---

## Highlights

| | What is different |
|---|---|
| **Delete-free memory** | The model proposes a typed plan. Deterministic code owns the mutation, caps how much may be archived, refuses to touch protected notes, and checkpoints the vault first. |
| **Lexical retrieval, measured** | BM25 over Hangul-aware tokens, Ebbinghaus decay, Hebbian potentiation, zone-priority EMA, and a Gaussian recency prior. No encoder, no vector store, benchmark harness in the repo. |
| **A graph runtime, not a spawn tool** | `agent`, `parallel`, and `pipeline` are code primitives. One workflow can cross Claude, Codex, and OpenAI-compatible models without naming any of them in the script. |
| **Bounded workers** | Six named workers, each with one trigger and one authority ceiling. Ceilings live in the executor, not the prompt. |
| **Approval before consequence** | Destructive shell work is refused or queued, and a denial carries your reason back so the agent corrects instead of retrying blind. A model never approves its own shell command. |
| **Fail-closed mutation** | Mutating tools checkpoint first or refuse to run. Resume reuses a cached call only when its sequence and a hash of prompt plus call options both still match. |
| **Korean as a first language** | Hangul bigram retrieval, Korean date cues and schedules, CJK-correct terminal widths. Tested in Korean rather than localized afterward. |
| **Terminal, Telegram, MCP** | Same vault, same control plane, three surfaces. Only safe reversible tools cross into Claude Code. No shell. |
| **Zero-dependency core** | One stdlib Python package you can read in an afternoon. No Node, no Docker, no vector database. |

---

## Graph engineering, not agent theater

Most agent systems keep control flow inside the prompt. The model decides
whether to call another model, whether to retry, when to stop. That is a
suggestion loop with a spawn button. Moirai moves those decisions into an
execution graph that Python owns.

```mermaid
flowchart LR
    E["Explicit entry<br/>CLI or slash command"] --> S["Load Python workflow"]
    S --> B["Bind roles to providers<br/>before execution"]
    B --> G{"Atropos guard"}
    G -->|within abort / budget / spawn limits| X{"Graph primitive"}
    G -->|limit reached| Z["Stop spawning"]
    X --> A["agent()"]
    X --> P["parallel()<br/>barrier"]
    X --> L["pipeline()<br/>per-item stages"]
    A --> J["Lachesis journal"]
    P --> J
    L --> J
    J --> O["Result + failure forensics"]
    J -. "matching sequence + call key" .-> R["Deterministic resume cache"]
    R -.-> X
```

- **Python owns control flow.** A workflow is a file with `meta` and `main(m)`.
  No tool exposes Moirai to a model, so a model cannot start one, and a test
  enforces that. [Engine contract](./birkin/moirai/engine.py).
- **Roles are portable. Authority is not.** The picker resolves every binding
  before the run. A per-call override wins, an undeclared role fails before it
  can spawn. [Binding ladder](./birkin/moirai/bindings.py).
- **Concurrency has semantics.** `parallel()` is a barrier. `pipeline()` lets
  each item advance through stages on its own. A failed branch returns `None`
  and its siblings keep going.
- **Replay is selective.** Resume accepts a cached call only when the sequence
  and the content-derived key both match, so rebinding one role re-runs that
  role and nothing else.
- **Failure is data.** Provider errors, schema misses, guard blocks, tokens,
  elapsed time, and tracebacks go into the run record instead of collapsing
  into "agent failed".

The bundled `deep-research` pattern is the same discipline pointed at search.
It saturates orthogonal axes in parallel, expands only on new leads, and stops
after two consecutive dry waves because `DRY_WAVES_TO_STOP` is a constant, not
a vibe. Surviving claims then go to a different model family to be refuted, and
anything unsettled is reported as unresolved rather than promoted into the
answer. [Pattern source](./birkin/moirai/patterns/deep_research.py).

---

## Workers with bounded authority

![Bounded execution lanes sharing one journal](./docs/assets/birkin-bounded-workers.png)

The workers are named after Greek figures. Their boundaries are deliberately
unromantic.

| Worker | Runs when | Authority ceiling |
|---|---|---|
| **Moirai** | You start a workflow, explicitly, from the CLI | Runs provider-portable graphs. Abort, token budget, and the 100-agent spawn cap are checked before each new agent. |
| **Mnemosyne** | Memory is searched or mechanically maintained | Owns zones, ranking, decay, links, indexes. No model call anywhere in it. Semantic curation is a separate layer with its own gate. |
| **Neurosis** | A request is too ambiguous to act on | Interviews one question at a time, writes a spec, waits for approval. It does not guess. |
| **Morpheus** | Nightly at 04:00, or on demand | Applies reversible memory and skill edits. No shell. Attempts to change birkin's control plane are queued behind manual approval, so no command or hook is activated without explicit human consent. |
| **Companion** | A commitment you made comes due | Proposes only. Activation happens in the approval executor, never in the reminder path. |
| **Harness** | Continual review finds a durable improvement | Memory and skill edits may self-apply under policy. Prompt and subagent edits are queued at the high tier and wait for `birkin review`. |

One rule generates that whole table. **Workers produce evidence and proposals.
Deterministic code owns ceilings, persistence, and approval.** It is why the
curator has no delete, why Moirai has no model-facing entry point, and why
Morpheus runs all night without a shell.

<sub>Section artwork was generated with
<a href="https://github.com/NomaDamas/god-tibo-imagen">god-tibo-imagen</a>.
The architecture diagram stays Mermaid so its labels remain inspectable and
diffable.</sub>

---

## Install

**macOS / Linux**
```bash
curl -fsSL https://raw.githubusercontent.com/ashmoonori-afk/birkin/main/scripts/install.sh | bash
```

**Windows (PowerShell)**
```powershell
irm https://raw.githubusercontent.com/ashmoonori-afk/birkin/main/scripts/install.ps1 | iex
```

**From source**
```bash
git clone https://github.com/ashmoonori-afk/birkin && cd birkin
uv run birkin            # or:  pip install -e .  &&  birkin
```

Python 3.10+. The first run opens an onboarding wizard.

### What it runs on

birkin drives a model you already have. Product features work across backends,
but the execution and permission boundary differs between Birkin's native tool
loop and external Claude/Codex CLI tool loops.

| Backend | How | Cost |
|---|---|---|
| **Claude Code** (`claude`) | be logged into `claude`, pick it in `birkin model` | your Claude subscription |
| **Anthropic API** | `export ANTHROPIC_API_KEY=sk-ant-…` | per token — `birkin budget` shows the month in dollars |
| **OpenAI-compatible** | provider `openai` + `base_url` (works with **Ollama**) | per token, or free locally |
| **Codex CLI** (`codex`) — *default* | be logged into `codex`; birkin uses the CLI's OAuth session | your ChatGPT subscription |

`birkin auth codex login` signs birkin in to Codex with its own OAuth session —
one in-process HTTPS call per request, no `codex` subprocess, and the `codex`
CLI does not even have to be installed. birkin keeps that credential in
`$BIRKIN_HOME/codex-auth.json` and **never writes `~/.codex/`**: OpenAI rotates
the refresh token on every grant, so sharing one credential between two clients
logs the other one out. Without a birkin login, `codex` still falls back to the
CLI. `birkin auth codex status` shows which session is in use.

The gateway keeps one warm process per conversation, so replies after the first
are model-time (**~3 s**) rather than a cold start per message.

When Birkin runs a `codex app-server` child, it disables Codex plugin hooks
for that child while leaving plugins and MCP servers available. This prevents
global `UserPromptSubmit` hooks from treating Birkin's internal
`<system-context>` as user text.

### Model-aware presets and tool boundaries

Birkin resolves the effective model before building its prompt and tools.
Known model families receive a small role overlay; unknown models use an
explicit neutral preset. Restricted native presets omit denied tool groups from
the registry, so those tools are neither advertised nor executable. A live
`/model` change and a `subagent_model` both rebuild that registry from the newly
selected model.

External Claude/Codex CLI agents own their tool loop, so the same preset text is
**advisory**, not an authorization control. Their sandbox and permission mode
remain the real boundary. Birkin passes the effective model into its attached
MCP server so MCP tool exposure follows the same preset. Custom
`model_presets` may change role/style and add denials, but cannot remove a
built-in restriction.

> On subscription vs. API key — including which surfaces run unattended and
> what that means for your plan's terms — see
> [`docs/DECISIONS.md`](./docs/DECISIONS.md) ADR-050 / ADR-051. birkin states
> its posture rather than leaving you to discover it.

---

## 🧠 The vault

Memory is **Mnemosyne**: a memory palace at `~/.birkin/vault`, built out of
files rather than vectors.

Notes live in **zone** directories and carry `type`, `polarity`
(positive / known-failure), `version` (optimistic lock), TTL and
`[[wikilinks]]`. Retrieval is an inverted index with **Okapi BM25** — idf-weighted
queries, Hangul bigrams, an **Ebbinghaus forgetting curve** folded into the
score, and a date prior so *"지난주에 정리한 배포 노트"* finds last week's note.

```bash
you > /remember I prefer concise replies, no preamble
birkin > Noted as [[Profile - reply-style]].

you > /memory 배포 파이프라인
```

Tools: `memory_search` (best-window snippets — a cheap preview layer),
`memory_get_note` (full text on demand), `memory_write_note`, `memory_link`.
Set `evidence_required: true` to refuse sourceless notes. Secrets are masked
before a note is written, not after.

**Measured, not asserted** (see [Research](#-research)): retrieval at parity
with a tuned embedding hybrid **with no encoder at all**, and per-query context
cost **371× below** loading the vault wholesale.

### Curation that cannot delete

Each night the curator may propose only `rezone`, `link`, `supersede`,
`archive`, and `annotate`. There is no delete operation to emit. Then a
deterministic executor decides what survives: archiving is capped at a fraction
of the vault, protected and negative-polarity notes are untouchable, a rezone
cannot smuggle a note into the archive, and invented note names are dropped.

`annotate` lets the curator write **retrieval anchors** — synonyms, phrasings
you might search for, cross-language keywords — into a note's frontmatter, so a
note becomes findable by words it does not literally contain. The body is not
addressable by that operation at all; only three whitelisted fields are, and
their length and count are clamped by code rather than trusted.

```bash
birkin curate-memory --dry-run   # show the plan; touch nothing
birkin curate-memory             # snapshot the vault, then apply the safe ops
```

This is the difference between "the agent is instructed not to delete your
notes" and "deletion is not expressible". Free-form read-modify-write memory can
wipe itself; this shape cannot.

### Your conversations, too

```bash
birkin sessions export <name> --vault
```

Transcripts become Obsidian-shaped notes in your vault — the same files, the
same folder, the same ownership.

---

## 🔌 Use the vault from Claude Code

The vault is not locked inside birkin. It ships as an ordinary stdio MCP
server, so any MCP host can mount it:

```bash
/plugin marketplace add ashmoonori-afk/birkin
/plugin install birkin-vault@birkin
```

or, without the plugin layer:

```bash
claude mcp add birkin -- birkin mcp-serve
```

Claude Code then has `memory_search`, `memory_get_note`, `memory_write_note`,
`memory_link`, `market_quote` and the skill tools — the vault, the ranking and
the wikilink graph, without leaving Claude Code. Only safe, reversible tools
cross that boundary: **no shell**, and consequential proposals still route to
the approval queue.

It composes with Claude Code's own memory rather than competing with it. Claude
Code writes per-repository project notes; the vault is your life across
projects. Point `autoMemoryDirectory` at a subfolder of the vault and both write
into the same folder you own.

---

## 🧵 Moirai — workflows across model families

The bundled **hard-task** pattern (`birkin moirai run hard-task --args '{"task": "..."}'`) decomposes a hard task into an internal todo list, executes it step by step, folds discovered follow-ups back into the list (bounded — anything dropped is named in the report), and announces each step through the progress channel chat heartbeats render — an approved long run reads `할 일 3/7 · 진행 중: …` in Telegram instead of silence.

A model deciding for itself whether to spawn another agent is not
orchestration. Moirai is: a workflow is a Python file, control flow is code,
and each agent is routed to whichever model should answer it.

```bash
birkin moirai run cross-examine --args '{"topic": "..."}'
```

The bundled `cross-examine` pattern has codex draft a claim, three claude
critics attack it from different angles **in parallel**, then codex revise.
Measured on one run: 71 s wall for 191 s of work.

A script declares *roles*, not models:

```python
meta = {
    "name": "cross-examine",
    "roles": {
        "drafter": {"default": "codex:gpt-5.6-sol", "hint": "makes the claim"},
        "critic":  {"default": "claude:haiku", "hint": "attacks it"},
    },
}

def main(m):
    draft = m.agent("Argue for X", role="drafter")
    votes = m.parallel([lambda a=a: m.agent(f"Attack via {a}: {draft}",
                                            role="critic")
                        for a in ("facts", "assumptions", "counterexamples")])
    return m.agent(f"Revise given {votes}", role="drafter")
```

**Who runs each role is decided before the run.** The launcher asks — keep the
current binding, reuse last run's, take the script's default, or browse
provider then model — and `--bind critic=claude:opus` pins one from the command
line. `--defaults` skips the asking; an unattended surface never prompts.

Before it starts, the launcher shows what will happen — deliberately not in
dollars, since birkin's usual path is a CLI login where a per-token price does
not exist:

```
  drafter → codex:gpt-5.6-sol     ●●○   12초 ×1        중량
  critic  → claude:opus           ●●●   62초 ×3        중량
  ─────────────────────────────────────────────────────
  합계                            예상 3분 18초 · 에이전트 4
```

Weight is a relative grade that cannot go stale on a reprice; the duration is
the median **this machine** actually recorded for that model (a published
figure marked `~` until your first run replaces it); a budget column appears
only if you set a token cap.

Other pieces: `schema=` returns validated data (codex enforces it natively,
everyone else is asked in the prompt and checked, with one retry); every call
is journalled, so `birkin moirai resume <id>` replays until the first thing
that actually changed — rebind one role and only that role's calls re-run.
A failed agent returns `None` rather than ending the workflow.

Entry is always explicit — CLI only. No tool lets a model start a workflow,
because that is the one spawn path with no natural ceiling. Agents are
text-only today; tool-bearing agents are refused with a clear message rather
than silently downgraded.

### Research that keeps going until it runs dry

```bash
birkin moirai run deep-research --args '{"question": "..."}'
```

`deep-research` splits a question into orthogonal axes, investigates them in
parallel, then follows every lead the answers opened — and keeps doing that
until two consecutive waves turn up nothing new. Claims are then handed to a
*different model family* to refute; anything it cannot settle is reported as
unresolved rather than promoted into the answer.

The algorithm is adapted from oh-my-openagent's `ulw-research` (MIT, credited
in the file). Note the honest limit: Moirai agents are text-only for now — the
`web_search` below belongs to birkin's own agent, not to them — so a web-heavy
question here leans on what the bound model knows plus what its own CLI can
reach.

### Letting birkin suggest a workflow

Off by default. With `"moirai_auto": true`, a request that would genuinely be
better as several parallel agents gets *proposed* rather than answered — and
the proposal lands in the same `birkin review` inbox as everything else
consequential:

```
🧵 세 접근 비교
   세 갈래를 병렬로 파는 게 낫다
   워크플로우: deep-research
```

The model judges and proposes; it still cannot start one. No tool exposes
Moirai to a model, and a test enforces that. Turning this on reverses a
deliberate 2026-07-07 decision to stop auto-detecting intent, which is why it
takes an explicit config change.

Design notes: `docs/moirai-design.md`.

---

## 🔒 Safety by construction

**Every shell command asks first. Every memory edit leaves a diff.**

The industry is moving the other way — the largest open agent now has an LLM
reviewer approve flagged commands by default. birkin deliberately does not: a
model never approves its own shell command.

- **run_shell approval gate.** `rm -rf`, `curl | sh`, force-push and friends are
  refused outright or queued for you when nobody is watching. Pattern-based — a
  seatbelt, not a sandbox — and a permanent allowlist never matches a compound
  command.
- **Native-tool blocks become exact manual operations.** Disabled-tool policy,
  workspace/egress file policy, control-plane writes, OS permission errors, Git
  `safe.directory`, and PowerShell execution policy queue the exact tool, input,
  working directory, gate, and digest. Approval permits one exact retry without
  elevation flags or global policy changes. HARDLINE shell commands, malformed
  input, authentication failures, and secret/SSRF egress blocks remain
  non-approvable integrity boundaries.
- **Denials teach.** `/deny <id> <why>` sends your reason back to the agent, so
  it corrects course instead of retrying a variant blind. Human-in-the-loop only
  wins if the loop converges.
- **Workspace checkpoints, fail-closed.** Every mutating tool snapshots the
  workspace into a bare git store *outside* your project first, so `/rollback`
  undoes a bad edit. If that snapshot cannot be taken, the tool is refused
  instead of running unprotected, and a `/rollback` that cannot save the current
  state first reports why rather than proceeding. Your own `.git` and `.env` are
  never touched.
- **Scanned skill install.** `birkin skills install owner/repo` fetches into
  quarantine and scans for exfiltration, prompt injection and destructive
  patterns before anything lands.
- **cron can't launder shell.** An auto-approved `cron` job carrying a shell
  payload is still queued for review.
- **The gateway is never `--dangerously-skip-permissions`.** A reachable chat
  message cannot reach a fully-permissioned process.
- **There is no open Telegram bot.** Without
  `channels.telegram.allowed_chat_ids` the gateway refuses to start Telegram at
  all — no "warn once and run anyway" path. Past that gate, strangers are still
  never auto-saved or memorized: memory poisoning needs a door, and this one is
  shut.
- **Secret redaction** before disk and before memory; state written atomically,
  `0o600`. Optional **lifecycle hooks** can block a tool or inject context, each
  confirmed once before it ever runs.

Rationale per decision: [`docs/DECISIONS.md`](./docs/DECISIONS.md) ADR-029.

---

## 🇰🇷 Korean-first

Not a translation layer — the failure modes Korean input actually hits are what
gets fixed and regression-tested:

- **Retrieval**: Hangul runs + character bigrams, so search works without a
  morphological analyzer or an encoder.
- **Time**: `지난주`, `그저께`, `3일 전`, `작년` are parsed as date cues that
  bias ranking toward the week you mean.
- **Schedules**: `/remind 30분마다 메일 확인`, `매일 09:00`, `매주 월요일 09:00`,
  `1시간 후` — alongside the English forms.
- **Terminal**: every box, bar and column is measured in East-Asian display
  cells, so mixed Korean/English never breaks the layout.
- **Names**: an all-Hangul skill or note name gets its own identity instead of
  collapsing into a shared slug.

---

## 🎮 A day with birkin

### Clarity before action (Neurosis)

For a vague or complex request, birkin doesn't guess. It runs a Socratic
interview with ambiguity scoring, one question at a time, writes a spec, and
acts only after you approve.

```bash
you > /neurosis 회사 인스타 캠페인 새로 기획해줘
birkin > Round 0 | 구성요소 확인 …        # topology → targeted questions → spec
```

### Overnight self-improvement (Morpheus)

```bash
birkin daemon --install   # register the OS task (login/boot; cron + launchd + schtasks)
birkin morpheus --dry-run # preview; unsandboxed local-cli dry-run is refused
birkin review             # next morning: approve / reject, one by one
birkin trace <run-id>     # audit replay of any past turn
```

Memory and skill writes apply themselves — they are reversible local files.
Anything consequential waits for you, and that is enforced rather than merely
intended: Morpheus runs with no shell, and birkin's own control plane
(`config.json`, `cron.json`, `hooks_allowlist.json`, `hooks/`) is refused to
the file tools outright, so an unattended run cannot schedule a command or
pre-approve a hook to get shell back.

### On Telegram

```bash
birkin gateway            # HTTP + (optional) Telegram, warm and persistent
```

Same memory, same skills, same persona as the terminal — birkin attaches its own
tool server to the CLI child so the gateway can actually write to the vault, not
just read a digest of it. Long work is proposed
with **Approve** / **Reject** buttons before it starts, bound to the chat that
asked, with a heartbeat while it runs. A finished reply is recorded before it is
sent, so a crash in that window redelivers it instead of losing it.
When you explicitly ask for a generated file, the gateway uploads the
workspace file as a Telegram document instead of merely naming its local path.
Internal attachment markers stay out of streamed chat text, oversized files are
rejected before they are read, and failed text or document sends remain in the
outbox for restart-time retry. Attachment paths resolve against the gateway's
own cwd **and** every configured `workspace_roots` entry — the directories the
agent actually writes into — and anything outside those roots is still refused.
After a gateway restart, the first message of each conversation is seeded with
that conversation's saved transcript tail, so birkin remembers what you were
talking about before the restart (`/new` opts out and starts truly clean).
The in-chat heartbeat names the work stage ("조사 중", "할 일 3/7: …") for
ordinary and approved long-running turns alike, not just a minute counter.
From an explicitly allowed Telegram chat, `/omo list`, `/omo use <id>`,
`/omo send`, `/omo steer`, `/omo abort`, `/omo status`, and `/omo last`
control local OMO sessions; other chats are denied before the local controller
runs.

### Follow-through on what you committed to (Companion)

```bash
birkin companion policy --enable --tz Asia/Seoul   # opt in — off by default
birkin companion bind telegram:<chat-id>           # where check-ins arrive
birkin companion add --outcome "ship the draft" --at 2026-08-01T09:00
birkin companion list                              # what birkin is holding
```

Tell birkin you'll do something, and it asks you about it at the agreed time —
over Telegram, with one-tap answers (**done / blocked / later / stop / wrong**).
The answer is recorded and the next concrete step is captured, so a commitment
either closes or moves.

You can also just say it in chat — "ask me about the draft Monday 9am" — and
the model calls `companion_propose`, which lands in the same approval inbox as
every other consequential action (`birkin review`, or the gateway's buttons).
The model may only *propose* a candidate: activation happens in the approval
executor, every transition goes through `companion.py`'s functions, and the
state files are control-plane-protected from the file tools — so an LLM cannot
silently change what you're on the hook for, by any route. Contact is bounded by policy — quiet hours
(22:00–08:00 by default), one check-in a day, a 12-hour cooldown — and the
tapping chat is re-verified against the commitment's stored binding before any
state changes, because `callback_data` is client-supplied. State lives in
`~/.birkin/companion/` next to an append-only `events.jsonl` of transitions —
no conversation bodies, grep-able like everything else.

### Company tools (MCP)

```bash
birkin mcp                # MCP servers the gateway inherits (Notion, Drive, …)
birkin mcp add <name> …   # passes through to `claude mcp`
```

---

## 🖥️ Terminal UI

A real TUI in pure ANSI on the standard library — no curses, no rich, no
textual — CJK-aware, and it degrades cleanly: piped or `NO_COLOR` output carries
**zero escape codes**.

- **Live status line** at every turn boundary and on `/status`: model · provider
  · daemon heartbeat · budget gauge · pending approvals, each segment appearing
  only when it has news.
- **Tool-trace tree** nested under subagents, one line per tool with its own
  elapsed time; `/details` expands to full input and a result snippet.
- **Discoverability**: grouped `/help` (or just `?`), fuzzy `/`-completion
  (`/prm` → `/permission`), and contextual hints — a checkpoint announces
  `/undo` exactly when there is something to undo.
- **`/dash`**: full-screen mission control (sessions · cron · approvals · memory
  zones) with a three-fold terminal restore and a `--plain` / `--json` fallback.
  A pane that fails to load says so instead of rendering empty, and approving
  from it reports what the action actually did.

`birkin web` opens a monitoring workbench for runtime health, pending proposals,
scheduled jobs and installed skills. Chat and configuration stay in the CLI.

![Birkin WebUI monitoring workbench](docs/assets/webui-workbench.png)

---

## 🧯 Built for a long unattended run

- **Auto-compaction** — a conversation that would overflow the context window is
  summarized in place before the call, with an overflow-retry backstop, so a
  multi-day chat doesn't die on *"prompt is too long"*.
- **Provider failover** — on an auth, rate-limit or server failure the turn is
  served by a fallback model for a cooldown, then the primary is probed again.
- **Grace call** — when the turn budget trips mid-task, one final no-tools turn
  reports what was done and what remains instead of stopping cold.
- **Spill-to-disk** — oversized tool output is saved with a preview and a path
  rather than truncated away.
- **Mid-turn steering** — typing while the agent works injects an instruction
  without discarding in-flight work; Esc still interrupts.
- **Parallel reads** — independent read-only calls run concurrently; writers
  stay sequential.

---

## 📟 Commands

```bash
birkin                              # start chatting (first run → onboarding)
birkin gateway                      # warm service: HTTP + Telegram
birkin neurosis "<idea>"            # seed a deep interview (drive it with /neurosis)
birkin odyssey "<goal>"             # seed a goal-completion cycle (/odyssey)
birkin moirai run <script> [--bind role=provider:model] [--defaults]
birkin moirai list / status --run-id <id> / resume --run-id <id>
birkin companion <action> [...]     # commitments birkin follows up on (opt-in)
birkin sessions [export … --vault]  # list conversations · export as Markdown
birkin curate-memory [--dry-run]    # vault curation pass (preview or apply)
birkin morpheus [--dry-run]         # run the nightly routine now
birkin daemon [--install]           # Morpheus + cron scheduler
birkin review                       # approve / reject proposed actions
birkin runs / trace <id> / budget   # audit log · replay · tokens and cost
birkin skills [validate|sync|install owner/repo|scan <dir>]
birkin mcp [list|add|remove|…]      # company MCP servers
birkin mcp-serve                    # serve the vault to any MCP host
birkin model / permission / web     # backend · gates · monitoring
```

### In chat

`/help` (or `?`) lists everything, grouped. Line editor: **Ctrl+←/→** word
motion, **Ctrl-W** delete word, **Ctrl-U/Ctrl-K** clear to start/end, **↑/↓**
history, **Shift+Enter** newline, inline `/`-dropdown.

| Group | Commands |
|---|---|
| **Conversation** | `/new` · `/retry` · `/undo` · `/rollback` · `/compact` · `/clear` · `/status` · `/dash` |
| **Clarify** | `/neurosis [name]` · `/odyssey <goal>` |
| **Model** | `/model` · `/models [name]` · `/provider` · `/temp` |
| **Skills · tools** | `/skills` · `/skill <name>` · `/reload` · `/tools` · `/system` · `/mcp` · `/details` |
| **Memory** | `/memory <query>` · `/remember <text>` · `/vault` · `/learn` |
| **Persona** | `/soul` · `/personality` |
| **Autonomy** | `/morpheus` · `/review` · `/cron` · `/permission` |
| **Session** | `/save` · `/load` · `/sessions` |
| **System** | `/config` · `/update` · `/help` · `/quit` |

---

## 🔎 Web search without an account

birkin can look things up, not just fetch a URL you already have:

```
web_search  → Marginalia, then Mwmbl if it can't answer
web_fetch   → read one of the URLs it returned
market_quote → structured price, currency, market timestamp and source by symbol
```

Both are independent, non-commercial indexes with public HTTP APIs. There is
no account to create, no API key to paste, no card on file, and nothing extra
to install — the dependency count is still zero, because this is `urllib` and
`json`.

The trade is coverage, and it is stated in the tool description so the model
reads an empty result correctly: these indexes are strong on documentation,
blogs, forums and technical writing, and weak on news, shopping and local
queries. Search titles and snippets are discovery aids, not evidence.
`web_fetch` returns the final source URL, retrieval time, page-supplied
publication/update dates, and HTTP last-modified date with the source text.
Nothing is retried on a rate limit — the public key's bucket is shared with
every other birkin user, so a retry loop would degrade it for everyone.
Marginalia results carry their CC-BY-NC-SA 4.0 attribution into the output.

Set `MARGINALIA_API_KEY` (or `marginalia_api_key` in config) if you have your
own key; you do not need one.

The same research contract applies to every Birkin agent surface. An answer
using internet research must list the exact source URL and organization,
publication/update date, and retrieval date in Sources. Recency is determined
from dates and versions, never search rank. Important time-sensitive claims are
cross-checked against a second independent authoritative source when available.
If a page has no source date, Birkin says recency is unverified; if sources
conflict, it reports the conflict instead of guessing.

`market_quote` does not read quote articles or search snippets. It consumes
Yahoo's structured chart response for symbols such as `MSFT`, `NVDA`,
`005930.KS`, and `000660.KS`, returning price, currency, exchange-local `as_of`,
an `intraday`/`latest_close` status, previous close, day high/low, and the source
URL together. Values older than seven days or future-dated values are rejected
rather than labeled current.

---

## 🧩 Skills

A skill is a directory with a `SKILL.md` (frontmatter + markdown), compatible
with the agentskills.io / hermes standard. **55 bundled** under
[`skills/`](./skills) — research, software, writing, data, devops, marketing,
planning/**neurosis**, automation/**morpheus** · **odyssey** · **camoufox**,
creative/**codex-image-gen**, quality/**model-compare** — plus your own under
`~/.birkin/skills/`, which shadow the bundled ones by name.

`load_skill` pulls the full text on demand; `create_skill` / `improve_skill`
route through the approval gate; `birkin skills validate` lints frontmatter and
`py_compile`s bundled scripts; skills hot-reload on edit.

`birkin skills install` takes `owner/repo[/path]`, **a local directory**, or an
**https URL** to a `SKILL.md`. All three land in quarantine and are scanned
there first — only the way the bytes arrive differs.

The **grounded-citations** skill is worth naming: it drives `verify_citations`,
which checks each claim against the text actually fetched and names the ones no
source states. Skills that tell a model to cite cannot detect when it cited
something the page never said; this can.

---

## 🗣️ Persona

`~/.birkin/SOUL.md` — a warm, editable voice injected into every surface, read
fresh each turn in the REPL. `/personality warm|concise|mentor|direct` swaps
presets; `/soul` shows and edits it.

---

## ⚙️ Configuration

Everything lives under `~/.birkin` (override with `BIRKIN_HOME`):

```
~/.birkin/
├── config.json     # provider, model, gateway, autosave, neurosis, permissions…
├── vault/          # your Obsidian memory
├── skills/         # user- and agent-authored skills
├── sessions/       # auto-saved transcripts — Morpheus input
├── companion/      # commitments + check-in policy (state.json, events.jsonl)
├── specs/          # Neurosis interview specs
├── runs/           # per-turn and per-Morpheus summaries
├── ledger.jsonl    # append-only audit log
├── pending/        # actions awaiting your approval
└── status.json     # daemon heartbeat
```

Keys you'll actually touch:

```json
{
  "provider": "claude-cli",
  "model": "opus",
  "gateway_model": "sonnet",
  "gateway_polish_provider": "claude-cli",
  "gateway_polish_model": "sonnet",
  "gateway_persistent": true,
  "cli_timeout": 900,
  "cli_access": "workspace",
  "cli_network_access": false,
  "egress": {
    "enabled": true,
    "enforced": true,
    "max_bytes": 1048576,
    "destinations": {
      "trusted-api": {
        "url": "https://api.example.com/submissions",
        "method": "POST",
        "automatic": true,
        "content_types": ["application/json"],
        "max_bytes": 1048576,
        "auth_env": "EXAMPLE_SUBMIT_TOKEN"
      }
    }
  },
  "workspace_roots": ["/path/to/primary-workspace"],
  "autosave_transcripts": true,
  "neurosis_auto": true,
  "morpheus_hour": 4,
  "morpheus_provider": "",
  "auto_approve": ["memory", "skill"],

  "auto_compact": true,
  "context_window": 200000,
  "fallback_provider": "",
  "fallback_model": "",
  "shell_approval": "manual",
  "command_allowlist": [],
  "checkpoints": true,
  "hooks": {},
  "parallel_tools": true,
  "spill_threshold": 30000,
  "repl_typed_line": "steer",
  "redact_secrets": true,
  "api_keys": [],
  "lsp_servers": {},
  "a2a_enabled": false,

  "harness_enabled": true,
  "harness_turn_interval": 12,
  "harness_cooldown_min": 15,
  "harness_compact_review": true,
  "harness_max_edits": 12,
  "harness_prompt_budget": 20000,
  "harness_auto_approve": ["memory", "skill"],

  "channels": {
    "http": {"enabled": true},
    "telegram": {"enabled": false, "token": "", "allowed_chat_ids": []}
  }
}
```

When `gateway_polish_provider` is set, approved long-running Telegram results
receive an isolated, no-tools editorial pass. The Claude path is accepted only
when every URL and numeric fact survives; authentication or integrity failures
fall back to the original reply. `claude auth status` must report
`loggedIn: true`.

Telegram long-work proposals render as escaped HTML cards with one explicit
approve/reject row; the internal proposal envelope and its JSON are never the
user-facing message.

For a persistent Codex gateway, the first existing entry in
`workspace_roots` is the process cwd and `workspace-write` sandbox root. Put
the primary project first. This matters on Windows: using the user-profile
root can make the Codex sandbox fail every PowerShell, Git Bash, and Kaggle
CLI child with `SetTokenInformation(TokenDefaultDacl) failed: 1344`.
`submit_payload` is the default outbound-write path. It accepts inline JSON or
text, resolves only an exact destination name from `egress.destinations`,
canonicalizes and scans the final bytes before DNS or a socket, injects
destination-scoped authentication from `auth_env`, sends once, and writes
metadata-only intent/outcome records to
`~/.birkin/egress-receipts.jsonl`. Automatic transfer requires
`automatic: true`; unknown and non-automatic destinations are blocked. Profiles
are HTTPS/443 only, with a fixed method/path/content-type/byte cap and no
query, fragment, userinfo, proxy, or redirect. Normal `redact_secrets` settings
cannot disable this pre-send scan.

With the default `egress.enforced: true`, Birkin omits native `run_shell` and
`spawn_subagent` capabilities that could bypass the broker. Model-controlled
`web_fetch` URLs and `web_search` queries receive the same pre-network secret
scan while normal public research remains available. Setting `enforced` to
`false` restores those raw native capabilities and emits a security warning.

`cli_network_access` defaults to `false`. Turning it on grants the Codex child
raw network and bypasses inspected-egress destination and payload checks, so
Birkin emits a security warning. Workspace filesystem confinement and
`approval_policy="never"` remain in force, but raw network is an explicit
escape hatch, not the submission default. `cli_access: "full"` remains the
separate, dangerous host-access opt-in and is never inherited by the reachable
gateway.
`cli_timeout` is an idle window measured from validated lifecycle or delta
activity in the current conversation thread, including multi-agent child
turns; unrelated app-server status notifications do not extend it. If Codex
accepts a turn but emits no item at all, Birkin stops it after 120 seconds
instead of waiting through a long idle budget. A started item is shown
separately (`active: reasoning` in the server log, `추론 중` in Telegram)
without inflating completed-event or agent-message counts. Child-turn items
keep the parent alive, but only the parent turn can supply the final reply.
Gateway startup also migrates the Moirai journal and marks runs and calls left
`running` by a previous process as `stale`. Failed agent calls retain their
traceback, role, label, phase, and reason in `calls` and
`runs.result_json.failures`. A `CodexTurnTimeout` writes an `incidents` row with
elapsed time, partial length, last event kind, and event count. Gateway stdout
and stderr lines are UTC timestamped, and timed-out turns still enter the
self-improvement recorder; review input includes recent failed calls and
gateway incidents.
When Codex returns the unmistakable Trusted Access for Cyber enrollment block,
Birkin retries once with an explicit scope limited to the named public
competition, organizer-provided assets, and the local workspace. A second
block is returned unchanged; the retry never broadens access to real systems,
credentials, users, or production services.

The second block is the reliability and safety layer: auto-summarize before
overflow, provider failover, the destructive-command gate, workspace snapshots
for `/rollback`, lifecycle hooks, parallel reads, tool-output spill, and whether
a line typed mid-turn steers or interrupts.

The last four are newer:

- **`redact_secrets`** — every tool result passes one choke point, and
  credential material (vendor-prefixed keys, auth headers, JWTs, URL
  passwords, private-key blocks) is masked there *before* it reaches the
  model, the transcript, or a spill file on disk. Set `false` to opt out.
- **`api_keys`** — more than one credential for the same provider. A
  rate-limited key rotates to the next one here *before* `fallback_provider`
  switches provider and model; each exhausted key cools down on its own timer
  (5 minutes for a 401, an hour for a 429).
- **`lsp_servers`** — `{".py": ["pyright-langserver", "--stdio"]}`. After an
  edit, birkin asks that language server whether the file still compiles and
  reports only the problems *this edit* introduced. Empty means no server, no
  subprocess, and no change to the tool result.
- **`a2a_enabled`** — see below. Off by default.

### Agent2Agent (A2A v1.0)

Another agent can hand birkin a task over JSON-RPC, discovering it at
`/.well-known/agent-card.json` on the local web server. `message/send`,
`tasks/get` and `tasks/cancel`; streaming and push notifications are declared
**false** in the card rather than half-built.

It is **off by default, and off means invisible**: every A2A path returns a
plain 404, exactly as if the feature did not exist. This is an inbound
execution surface, so nobody acquires one by upgrading, and only a real
`true` turns it on — a `"false"` string will not. The RPC sits behind the same
`X-Birkin-Token` the dashboard already requires for POST; the card itself is
unauthenticated, because a peer has to read it before it has a token and it
carries nothing secret. A peer's task runs as a one-shot session, so it cannot
land in a conversation you are having.

### The continual harness

Self-improvement is no longer a blind write. Morpheus and the in-session review
emit a *proposal* — summary, rationale, expected outcome, and a list of edits —
and the harness validates it, applies it, and records what it did in a versioned
ledger under `~/.birkin/harness/`.

Four entry kinds are tracked: **`prompt`** (supplemental behaviour notes),
**`memory`**, **`skill`**, and **`subagent`** (reusable delegation specs). Every
entry carries a `version` and an `updated_at`, and every applied proposal is
appended to `refinements.jsonl` together with the `before` state of everything
it touched — so a change is a *reversible refinement* by construction, not by
hoping a backup exists.

`harness_auto_approve` decides what lands without asking. `memory` and `skill`
are reversible local files, so they apply themselves — the same policy
`auto_approve` already uses. `prompt` and `subagent` are not: they change how the
agent behaves on *every later turn*, so they are queued as `harness` proposals
(approval tier **high**) and wait for `birkin review`.

```bash
birkin harness show                  # current entries, by kind, with versions
birkin harness show --scope local    # the session-scoped harness instead
birkin harness history -n 20         # the refinement ledger, oldest first
birkin harness rollback <id>         # reverse one refinement, edit by edit
birkin harness export <path>         # write the harness state to a JSON file
birkin harness refine                # where proposals come from (see below)
```

`refine` writes nothing on its own — proposals come from `birkin morpheus` and
from the in-session review, and the ones that are not auto-approved wait in
`birkin review`. The command says so and exits rather than pretending to work.
An unknown refinement id makes `rollback` exit `1` with a one-line reason, not a
traceback.

- **`harness_enabled`** — the master switch. Off restores the old direct-write
  behaviour and puts no harness block in the system prompt.
- **`harness_turn_interval`** — assistant turns that must pass before the
  in-session review gate is even consulted; a gate on every turn costs a model
  call on every turn.
- **`harness_cooldown_min`** — minutes of quiet after a review runs.
- **`harness_compact_review`** — review at compaction time too: the moment older
  context is about to be summarized away is the last chance to keep what it
  taught.
- **`harness_max_edits`** — cap on the edits one proposal may carry. An
  unattended pass that "improves" forty things at once is a runaway, not a good
  night.
- **`harness_prompt_budget`** — character budget for the harness block inside
  the system prompt.
- **`harness_auto_approve`** — the kinds applied without asking; everything else
  is queued for `birkin review`.

Those are the *defaults* — `config.json` on disk holds only the keys you
actually changed, nested sections included. That matters on upgrade: a file that
mirrored every default would replay yesterday's values over a better default
forever, so `birkin update` could ship an improvement no existing install ever
received. Keys birkin does not recognize — legacy names, anything you added by
hand — are preserved untouched.

API keys are read from the environment first; a key in `config.json` is stored
`chmod 600`. Colour obeys `NO_COLOR` / `CLICOLOR_FORCE`; `BIRKIN_PLAIN=1` drops
animation for screen readers.

---

## 📄 Research

The memory engine is written up as a paper — *Birkin-Mnemosyne: A
Zero-Dependency Lexical Memory Palace with Safe, Provider-Portable Curation for
Personal LLM Agents* — with a reproducible harness under
[`benchmarks/`](./benchmarks). LongMemEval-S session retrieval, 470 questions,
one harness:

| system | R@1 | R@5 | MRR |
|---|---|---|---|
| BM25 + bigram | 0.870 | 0.968 | 0.910 |
| best embedding hybrid (RRF k=20, chunked bge) | 0.894 | 0.977 | 0.931 |
| **tuned lexical stack — no encoder** | **0.900** | **0.977** | **0.933** |
| **shipped in production today** | **0.891** | **0.974** | **0.926** |

Also measured: curation accuracy across engines (n=10, bootstrap CIs — including
a hidden second fixture that *reverses* the ranking, reported rather than
buried); a 1,910-note vault study; context cost (retrieval top-5 is **9.1×**
cheaper than long-context, **371×** cheaper than loading the vault wholesale);
and honest negatives — snippets cannot replace full-note reads, and BM25F field
weighting was implemented, measured as indiscriminable on every corpus
available, and reverted rather than shipped on a hunch. Research log:
[`docs/ranking-v2-plan.md`](./docs/ranking-v2-plan.md).

---

## 🛠️ Where birkin sits today

- **55 bundled skills**, **0 runtime dependencies**, Python 3.10+.
- Deliberately smaller than its inspirations —
  [hermes-agent](https://github.com/NousResearch/hermes-agent) and
  [openclaw](https://github.com/openclaw/openclaw). The deep-interview lineage
  comes from [gajae-code](https://github.com/Yeachan-Heo/gajae-code),
  model-aware prompt adaptation was informed by
  [senpi](https://github.com/code-yeongyu/senpi), and
  [shadcn/ui](https://github.com/shadcn-ui/ui) is the default component book
  for generated interfaces. Not competing on breadth: on the depth of the
  trust and memory story. See
  [`docs/COMPARISON.md`](./docs/COMPARISON.md), which lists where birkin loses.
- Every decision has a written rationale:
  [`docs/DECISIONS.md`](./docs/DECISIONS.md). Live status:
  [`docs/STATUS.md`](./docs/STATUS.md).

---

## 🙌 Contributing

Skills are the easiest place to start: a skill is just a directory with a
`SKILL.md` — copy any folder under [`skills/`](./skills), run
`birkin skills validate`, open a PR. Bug reports and feature requests are
welcome as issues.

Before any commit-and-push handoff, run the relevant CLI tests and manual CLI
smoke, update and cross-check both READMEs, and complete static plus targeted
security checks. The binding agent checklist lives in [`AGENTS.md`](./AGENTS.md).

If birkin is useful to you, **starring the repo** helps other people find it. ⭐

---

## 📄 License

**MIT** (© 2026 ashmoonori). Use it, fork it, ship it. Portions of the bundled
skill catalog are adapted from MIT projects — NousResearch/hermes-agent,
openclaw, and Yeachan-Heo/gajae-code — with attribution preserved. See
[`LICENSE`](./LICENSE) and [`NOTICE`](./NOTICE).
