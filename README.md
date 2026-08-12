# birkin

**A dependency-free Python agent that treats memory, execution, and
self-improvement as inspectable local state.**

birkin is a local-first CLI agent, HTTP/Telegram gateway, MCP server, and
multi-agent runtime. Its production package uses only the Python standard
library. The repository is roughly 32,000 lines of Python and ships with more
than 2,000 offline tests and 56 bundled skills.

The interesting part is not another chat loop. It is the way the code joins
the loop to operational machinery: resumable goals, isolated subagents,
workspace checkpoints, secret redaction, model failover, transparent Markdown
memory, deterministic multi-agent workflows, and a reversible
self-improvement ledger.

[한국어](./README.ko.md)

## Why birkin exists

There are already excellent general-purpose agent projects. birkin makes a
different trade:

- one installable Python package instead of a multi-language runtime;
- zero mandatory runtime dependencies instead of SDK-heavy provider stacks;
- visible files and append-only records instead of opaque hosted state;
- a small native tool surface instead of browser/computer automation;
- explicit approval, checkpoint, and redaction choke points around execution;
- bounded worker continuations that run only after explicit approval;
- continual improvement as reviewable proposals that can be rolled back.

This makes birkin unusually easy to audit, embed, test offline, and repair with
ordinary Python tools.

## Code-level comparison

The following comparison comes from the code in birkin and the current source
trees of
[hermes-agent](https://github.com/NousResearch/hermes-agent) and
[prime-agent](https://github.com/PrimeIntellect-ai/prime-agent), inspected on
2026-08-10. It does not rely on product claims or architecture documents.

| | birkin | hermes-agent | prime-agent |
|---|---|---|---|
| Main shape | One Python package | Large Python application plus JS/TS surfaces | TypeScript monorepo plus Python kernel shim |
| Approximate source scale | 32K Python LOC | 166K Python + 132K JS/TS LOC | 152K TypeScript LOC |
| Mandatory runtime dependencies | 0 | Large exact-pinned Python set plus extras | Multiple npm package dependency graphs; Python runtime uses IPython |
| Agent/tool organization | One native loop and one registry choke point | Broad provider, gateway, browser, media, and tool subsystems | Layered `ai`, `agent`, `coding-agent`, and `tui` packages |
| Memory | Editable Markdown/YAML/wikilink vault | Multiple state and memory integrations | Session/context-tree centric |
| Self-improvement | Versioned proposal ledger with validation and rollback | Broad skill and runtime ecosystem | Extension and package ecosystem |
| UI/channel breadth | CLI, WebUI, local HTTP, Telegram, MCP, A2A | Much broader browser, gateway, and messaging surface | Rich terminal UI and coding-agent extensions |
| Best fit | Small, auditable, long-running local agent | Feature breadth and many integrations | TypeScript-native coding-agent platform and TUI |

### Where birkin is stronger

**Small dependency and supply-chain surface.** `pyproject.toml` declares no
runtime dependencies. HTTP, streaming, JSON-RPC, cron parsing, persistence,
provider clients, and the native agent loop are implemented in the package.
Optional desktop screenshots use Pillow and pywin32 only when explicitly
enabled.

**A single enforcement path for tool results.** Every native tool call passes
through `ToolRegistry.run`. Hooks observe there; textual output is redacted
there; oversized text spills only after redaction; image bytes are kept out of
event payloads and spill files. The agent loop receives one typed
`ToolResult` shape.

**Self-improvement is data, not an invisible mutation.** `harness.py` accepts
typed proposals, validates their limits, records prompt/memory/skill/config
edits in a ledger, and supports rollback. `morpheus.py` produces proposals from
recent work instead of directly rewriting the agent. The same harness can run
at turn boundaries.

**Transparent memory.** `memory.py` stores YAML-frontmatter Markdown notes and
wikilinks in an Obsidian-compatible vault. `mnemosyne.py` supplies an LLM-free
index, zones, priority, and decay. Users can inspect and edit the knowledge
base without a vector database or migration tool.

**Failure handling is layered.** Provider calls can retry, rotate credentials
after rate limits, and fall back to another provider. Long conversations
compact automatically. Workspace edits can create checkpoints. Goal execution
persists a resumable Boulder plan instead of depending on one uninterrupted
process.

**One prompt assembly gate.** `promptgate.py` composes persona, memory, skills,
and runtime notices for every surface. The REPL, gateway, dry-run path, and
warm sessions do not each invent a different system prompt.

**Multi-agent work without a second runtime.** Isolated subagents, concurrent
read-only tool batches, deterministic Moirai workflows, A2A JSON-RPC, and MCP
all run from the same package and storage conventions.

### Where hermes-agent and prime-agent are stronger

birkin intentionally has less surface area.

- hermes-agent has far more gateway platforms, browser/computer-use code,
  provider adapters, media tools, and deployment integrations.
- prime-agent has a richer TypeScript package ecosystem, terminal UI,
  extension surface, browser-oriented build targets, and an IPython-backed
  coding runtime.
- birkin has no native browser automation and no equivalent to their full TUI
  stacks.
- birkin is primarily a single-process local runtime. It is not a distributed
  control plane.
- Native tools execute with the current user's authority. `shell_approval`,
  `fs_jail`, disabled tools, gateway authentication, and allowlists must be
  configured for the deployment rather than assumed.

Choose birkin when smallness, local inspectability, and reversible operation
matter more than integration breadth.

## Structural map

```text
birkin/
  agent.py          native tool-calling loop, compaction, parallel calls
  llm.py            provider protocol, streaming, retry and failover boundary
  runtime.py        constructs clients, prompts, registries, memory and skills
  promptgate.py     single system-prompt assembly point
  tools/            files, shell, web, vision, sessions, memory and subagents
  gateway/          local HTTP and Telegram channels
  memory.py         Obsidian-compatible semantic memory
  mnemosyne.py      mechanical memory index, zones and decay
  harness.py        validated self-improvement ledger and rollback
  morpheus.py       scheduled proposal generation
  moirai/           deterministic multi-agent workflow engine
  boulder.py        durable resumable goal plans
  checkpoints.py    workspace snapshots and restore
  shellguard.py     destructive-command approval
  security.py       deployment-facing security diagnostics
  a2a/              Agent2Agent JSON-RPC server
  web/              local WebUI server
skills/             56 bundled Markdown skills
tests/              offline unit, integration, gateway and e2e coverage
```

The structure is deliberately flat. Most behavior is a module with explicit
inputs and file-backed state rather than a framework hierarchy.

## Install

Python 3.10 or newer is required.

```bash
git clone https://github.com/ashmoonori-afk/birkin.git
cd birkin
python -m pip install -e .
birkin setup
```

For development:

```bash
python -m pip install -e ".[dev]"
pytest
```

## First run

```bash
# Guided setup
birkin setup

# Interactive agent
birkin chat

# Inspect models and native tools
birkin models
birkin tools

# Start the local gateway or WebUI
birkin gateway
birkin web
```

The default provider is Anthropic. API keys may be supplied through setup,
environment variables, or `~/.birkin/config.json`. Subscription-backed Claude
and Codex CLI providers are also supported when their CLIs are installed and
authenticated.

When birkin starts a `codex app-server` child, it disables Codex plugin hooks
for that child while preserving plugins and MCP servers. This keeps a global
`UserPromptSubmit` hook from treating birkin's internal `<system-context>` as
user input.

### Active voice control

Voice support is installed with birkin. OpenAI STT/TTS calls require a Platform
API key:

```bash
export OPENAI_API_KEY="..."
uv run birkin gateway
```

In another terminal, start continuous live-microphone voice mode:

```bash
uv run birkin voice start \
  --gateway-url http://127.0.0.1:8788/message
uv run birkin voice status
```

`start` waits for authenticated worker readiness, rejects duplicate daemons,
and writes its authenticated control state and log under `~/.birkin/voice`.
The state directory is restricted to the current OS account; keep any custom
`BIRKIN_HOME` on a filesystem that supports user ACLs. If a live daemon PID
temporarily stops answering, `start` reports it as `UNREACHABLE` instead of
deleting its state and launching an orphaned duplicate.
`status` reports the current PID and exits `0` only for `RUNNING`;
`STOPPING`, `UNREACHABLE`, and `INACTIVE` exit `1`. Stop the daemon after its
current bounded voice turn with:

```bash
uv run birkin voice stop
```

If that turn outlives the control wait, `stop` prints `STOPPING`, exits `1`,
and the accepted shutdown continues; poll with `voice status`.

Recorded and deterministic inputs remain one-shot only:

```bash
uv run birkin voice --once \
  --audio wake.wav \
  --command-audio command.wav \
  --gateway-url http://127.0.0.1:8788/message \
  --tts-output reply.pcm \
  --no-playback
```

For a one-shot live capture, omit `--audio` and `--command-audio`. Add
`--background` to receive a durable job receipt under
`~/.birkin/voice/jobs`. For deterministic CI or troubleshooting, provide
`--transcript "Daddy is home" --command "status"` instead. Daemon `start`
accepts live-microphone options only; file, transcript, command, background,
and `--once` inputs fail before a worker is launched.

The nested `voice` config block supplies defaults for the matching CLI flags;
an explicit flag wins. Its empty `gateway_url` keeps wake-only fixture runs
offline. For Gateway delivery, set it or pass `--gateway-url` with an exact
loopback HTTP `/message` endpoint such as
`http://127.0.0.1:8788/message`. Non-loopback hosts, HTTPS, credentials,
queries, and fragments are rejected. If the local HTTP channel is protected,
set `BIRKIN_HTTP_TOKEN`; the voice client forwards it only to that validated
loopback endpoint.

The wake phrase is a routing trigger, not authorization. Voice requests still
cross `Gateway.handle("voice", ...)` and cannot gain Telegram's approved-work
flags. `gpt-transcribe` performs bounded STT and `gpt-4o-mini-tts` produces the
reply audio; generated speech is AI-generated. Codex/ChatGPT sign-in does not
replace `OPENAI_API_KEY` for Audio API calls.


## Native tools

The registry can expose:

- workspace-scoped file read, edit, write, and listing;
- shell execution with destructive-command approval;
- HTTP fetch, web search, quote lookup, and citation verification;
- session lookup and transcript access;
- transparent memory operations;
- isolated subagents with scoped tool groups;
- skill loading, creation, and refinement;
- `vision_analyze` for local or HTTP(S) PNG, JPEG, GIF, and WebP images;
- opt-in Windows window listing and screenshot capture.

Remote images use the same private/reserved-address and redirect checks as web
fetching. Desktop tools are absent from the registry unless
`desktop_tools` is exactly `true`.

## Configuration

Configuration lives at `~/.birkin/config.json` or under `BIRKIN_HOME`. This is
a representative configuration using real defaults from `birkin/config.py`:

```json
{
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "subagent_model": "claude-haiku-4-5-20251001",
  "api_key": null,
  "api_keys": [],
  "max_tokens": 4096,
  "temperature": 1.0,
  "max_turns": 24,
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
  "context_window": 200000,
  "auto_compact": true,
  "fallback_provider": "",
  "fallback_model": "",
  "fallback_cooldown": 300,
  "parallel_tools": true,
  "max_depth": 2,
  "shell_approval": "manual",
  "command_allowlist": [],
  "fs_jail": false,
  "checkpoints": true,
  "checkpoint_keep": 20,
  "redact_secrets": true,
  "spill_threshold": 30000,
  "disabled_tools": [],
  "desktop_tools": false,
  "self_improve": true,
  "a2a_enabled": false,
  "lsp_servers": {},
  "harness_enabled": true,
  "harness_turn_interval": 12,
  "harness_cooldown_min": 15,
  "harness_compact_review": true,
  "harness_max_edits": 12,
  "harness_prompt_budget": 20000,
  "harness_auto_approve": ["memory", "skill"],
  "web_port": 8787,
  "gateway_port": 8788,
  "budget_tokens_daily": 0,
  "budget_tokens_monthly": 0,
  "voice": {
    "wake_phrase": "Daddy is home",
    "gateway_url": "",
    "session_id": "voice-local",
    "sample_rate": 24000,
    "stt_model": "gpt-transcribe",
    "tts_model": "gpt-4o-mini-tts",
    "tts_voice": "coral",
    "tts_instructions": "Speak concisely and clearly.",
    "background_workers": 2
  },

  "channels": {
    "http": {"enabled": true},
    "telegram": {
      "enabled": false,
      "token": "",
      "allowed_chat_ids": [],
      "stream": true
    },
    "slack": {"enabled": false, "webhook_url": ""},
    "discord": {"enabled": false, "webhook_url": ""}
  }
}
```

Important boundaries:

- `shell_approval: "manual"` asks before destructive shell commands.
- On Windows, shell jobs use `cmd.exe` and receive a verified writable
  `TEMP`/`TMP`, so tools such as Bun and npm keep working in long-lived
  gateway, scheduler, and daemon processes. PowerShell is used only when
  explicitly requested.
- `fs_jail: true` restricts native file tools to configured workspace roots.
- `redact_secrets: true` masks detected credentials before output is persisted.
- `disabled_tools` removes named native tools from the registry.
- Gateway exposure should be paired with HTTP authentication or Telegram
  `allowed_chat_ids`.
- Slack and Discord are send-only adapters. They require HTTPS incoming-webhook
  URLs and truncate messages at 3,500 and 2,000 characters respectively.
- Daily/monthly token budgets are disabled when set to `0`.

Run `birkin setup` for guided configuration and `birkin tools` to inspect or
toggle the effective tool set.

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

## Memory and self-improvement

birkin's memory is a directory of normal Markdown files. Notes remain usable
without birkin and can be versioned with Git.

The improvement path is deliberately separate:

1. recent work is reviewed;
2. the reviewer emits bounded edits;
3. the harness validates target, type, and budget;
4. approved edits are applied and appended to the ledger;
5. an entry can be inspected or rolled back.

Useful commands:

```bash
birkin harness
birkin harness history
birkin morpheus
birkin nightly
birkin curate
birkin curate-memory
```

## Multi-agent and protocol surfaces

- **Subagents** receive a fresh conversation, scoped tools, and optional
  skills. They do not inherit the parent's transcript or write to its memory.
- **Moirai** executes deterministic workflows across Claude, Codex, and API
  workers.
- **Boulder/Odyssey** persist and verify long-running goal steps.
- **MCP** exposes birkin tools to compatible clients.
- **A2A** exposes an opt-in Agent2Agent v1.0 JSON-RPC endpoint and agent card.
- **Gateway** keeps sessions warm across local HTTP and Telegram turns.
- **Structured actions** reuse the approval queue for channel-neutral questions.
  Every question has an action id, explicit expiry, typed radio or checkbox
  options, optional clarification, and recommendation metadata. The first valid
  answer wins atomically; stale, malformed, or expired replies return
  `reply_rejected`.

The WebUI approval inbox renders structured actions as accessible controls. A
successful submission changes the card in place to a resolved, disabled
outcome. Non-browser channels can render the same contract as numbered text.

## Integration workflows

Durable subagent runs are visible in `/dash` and the REPL:

```text
/agents
/attach <run-id>
/send <run-id> <message>
```

Use `/goal set <objective> [--budget N] [--gate "command"]` to persist one
active goal. `/goal show`, `/goal pause`, and `/goal done` manage it. A gate
command is never executed directly by the goal store; finishing the goal routes
the verifier through the existing shell approval queue.

`/sessions <query>` searches saved transcripts and returns date, channel,
model, snippet, and score metadata. Filters compose with AND:
`--since 30d`, `--from telegram` (also `--channel`), and `--model <name>`.
Bare `/sessions` keeps the original saved-session listing.

Cron jobs may use `"type": "monitor"` with exactly one of `monitor_url` or
`monitor_script`. They alert only when the bounded result changes; URL monitors
apply the web SSRF guard, a 30-second timeout, and a 256 KiB maximum response.
Fetch failures are recorded as failures, not changes.

## Verification

The default test run is offline:

```bash
pytest
```

At the time of this rewrite the suite passes more than 2,300 tests with over
82% package coverage. Live-provider tests are excluded by default and require
`BIRKIN_LIVE=1`.

Static checks used by the project:

```bash
python -m ruff check .
python -m bandit -r birkin
```

## License

birkin is released under the [MIT License](./LICENSE).
