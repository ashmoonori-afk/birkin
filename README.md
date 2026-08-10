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
  "channels": {
    "http": {"enabled": true},
    "telegram": {
      "enabled": false,
      "token": "",
      "allowed_chat_ids": [],
      "stream": true
    }
  }
}
```

Important boundaries:

- `shell_approval: "manual"` asks before destructive shell commands.
- `fs_jail: true` restricts native file tools to configured workspace roots.
- `redact_secrets: true` masks detected credentials before output is persisted.
- `disabled_tools` removes named native tools from the registry.
- Gateway exposure should be paired with HTTP authentication or Telegram
  `allowed_chat_ids`.
- Daily/monthly token budgets are disabled when set to `0`.

Run `birkin setup` for guided configuration and `birkin tools` to inspect or
toggle the effective tool set.

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
