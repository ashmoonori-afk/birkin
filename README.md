# birkin

A lightweight, **self-improving CLI agent workspace** with skill management,
subagents, and an optional WebUI.

Inspired by [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
(skills system, self-improvement loop, subagents) and
[openclaw/openclaw](https://github.com/openclaw/openclaw) (gateway/CLI,
skillsets, control UI), distilled down to a **zero-dependency** core.

## Why birkin

- **Zero runtime dependencies** — Python standard library only.
- **Skill-native** — uses the `SKILL.md` format compatible with the
  [agentskills.io](https://agentskills.io) / hermes standard, so skills are
  portable.
- **Self-improving** — the agent can author and refine its own skills from
  experience and keep a persistent memory of who you are.
- **Subagents** — spawn isolated agents for parallel sub-tasks with a scoped
  toolset.
- **CLI-first, WebUI-optional** — chat in the terminal or open a local web chat.

## Requirements

- Python **3.10+** (developed on 3.13)
- An LLM API key. By default birkin uses the Anthropic Messages API:
  ```
  set ANTHROPIC_API_KEY=sk-ant-...      # Windows (PowerShell: $env:ANTHROPIC_API_KEY="...")
  export ANTHROPIC_API_KEY=sk-ant-...   # macOS/Linux
  ```

## Install / run

From this directory:

```bash
# Run in place (recommended during development)
uv run birkin            # or:  python -m birkin

# Or install
pip install -e .
birkin
```

## Commands

```
birkin                 # start interactive chat (REPL)
birkin chat            # same as above
birkin skills          # list available skills
birkin skills <name>   # show a skill's full content
birkin web             # launch the local WebUI (default http://127.0.0.1:8787)
birkin setup           # configure provider / model / key
```

### In-chat slash commands

```
/help        show commands
/skills      list loaded skills
/new         start a fresh conversation
/model       show / change the model
/save        save the current session
/quit        exit
```

## Configuration

State lives under `~/.birkin` (override with `BIRKIN_HOME`):

```
~/.birkin/
├── config.json     # provider, model, options (no secrets required here)
├── memory.json     # persistent user profile + facts
├── skills/         # user- and agent-authored skills (writable)
└── sessions/       # saved conversations
```

Bundled skills ship in this repo's [`skills/`](./skills) directory.

## Skill format

Each skill is a directory containing a `SKILL.md` file with YAML-style
frontmatter, compatible with hermes:

```markdown
---
name: web-research
description: "Research a topic on the web and synthesize a sourced summary."
version: 1.0.0
metadata:
  birkin:
    tags: [research, web]
---

# Web Research

## When to Use
...

## When NOT to Use
...
```

## Architecture

```
birkin/
├── bin entry (pyproject script) -> birkin.cli:main
├── birkin/
│   ├── cli.py          # argparse subcommands: chat | skills | web | setup
│   ├── config.py       # paths, config load/save, key resolution
│   ├── llm.py          # provider-agnostic client (Anthropic default, via urllib)
│   ├── agent.py        # tool-calling loop
│   ├── tools/          # files, shell, web, subagent
│   ├── skills/         # frontmatter parser, loader, manager
│   ├── subagent.py     # isolated agent runner
│   ├── selfimprove.py  # post-task reflection -> skill authoring
│   ├── memory.py       # persistent memory store
│   ├── repl.py         # interactive chat
│   └── web/            # http + SSE server, static chat UI
└── skills/             # bundled SKILL.md skills
```

## Status

v0.1 — core loop, skills, subagents, self-improvement, CLI and WebUI. See
`birkin --help`.

## License

MIT
