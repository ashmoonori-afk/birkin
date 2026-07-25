# birkin-vault

Your memory vault, inside Claude Code.

```
/plugin marketplace add ashmoonori-afk/birkin
/plugin install birkin-vault@birkin
```

## What you get

Claude Code gains birkin's memory tools over MCP:

| Tool | What it does |
|---|---|
| `memory_search` | BM25 search over your vault (Korean-aware; idf-weighted queries, relative-date cues like "지난주") |
| `memory_get_note` | Read one note in full |
| `memory_write_note` | Write a note — Markdown, frontmatter, `[[wikilinks]]` |
| `memory_link` | Link two notes |
| `memory_related` | Mechanical link candidates for a note |
| `memory_rezone` | Move a note between zones |
| `skills_list` / `load_skill` | birkin's bundled skills |
| `propose_action` | Queue a consequential action for your approval |

The vault is a folder of Obsidian-compatible Markdown under `~/.birkin/vault`.
Open it in Obsidian, edit it by hand, put it in git — it is yours, and it
outlives both birkin and this plugin.

## What does not cross the boundary

No shell. Consequential proposals go to birkin's approval queue rather than
executing. See the security section of the [birkin README](../../README.md).

## Requirements

`birkin` on your PATH (`pip install -e .` from the repo, or the install
script). The plugin runs `birkin mcp-serve`, which is a stdio MCP server with
zero runtime dependencies.

## Alongside Claude Code's own memory

This is not a replacement for Claude Code's per-repository auto memory. Point
`autoMemoryDirectory` at a subfolder of the vault and both write into the same
folder you own.
