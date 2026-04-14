---
sidebar_position: 4
title: "Toolsets Reference"
description: "Reference for Birkin core, composite, platform, and dynamic toolsets"
---

# Toolsets Reference

Toolsets are named bundles of tools that control what the agent can do. They're the primary mechanism for configuring tool availability per platform, per session, or per task.

## How Toolsets Work

Every tool belongs to exactly one toolset. When you enable a toolset, all tools in that bundle become available to the agent. Toolsets come in three kinds:

- **Core** — A single logical group of related tools (e.g., `file` bundles `read_file`, `write_file`, `patch`, `search_files`)
- **Composite** — Combines multiple core toolsets for a common scenario (e.g., `debugging` bundles file, terminal, and web tools)
- **Platform** — A complete tool configuration for a specific deployment context (e.g., `birkin-cli` is the default for interactive CLI sessions)

## Configuring Toolsets

### Per-session (CLI)

```bash
birkin chat --toolsets web,file,terminal
birkin chat --toolsets debugging        # composite — expands to file + terminal + web
birkin chat --toolsets all              # everything
```

### Per-platform (config.yaml)

```yaml
toolsets:
  - birkin-cli          # default for CLI
  # - birkin-telegram   # override for Telegram gateway
```

### Interactive management

```bash
birkin tools                            # curses UI to enable/disable per platform
```

Or in-session:

```
/tools list
/tools disable browser
/tools enable rl
```

## Core Toolsets

| Toolset | Tools | Purpose |
|---------|-------|---------|
| `browser` | `browser_back`, `browser_click`, `browser_console`, `browser_get_images`, `browser_navigate`, `browser_press`, `browser_scroll`, `browser_snapshot`, `browser_type`, `browser_vision`, `web_search` | Full browser automation. Includes `web_search` as a fallback for quick lookups. |
| `clarify` | `clarify` | Ask the user a question when the agent needs clarification. |
| `code_execution` | `execute_code` | Run Python scripts that call Birkin tools programmatically. |
| `cronjob` | `cronjob` | Schedule and manage recurring tasks. |
| `delegation` | `delegate_task` | Spawn isolated subagent instances for parallel work. |
| `file` | `patch`, `read_file`, `search_files`, `write_file` | File reading, writing, searching, and editing. |
| `homeassistant` | `ha_call_service`, `ha_get_state`, `ha_list_entities`, `ha_list_services` | Smart home control via Home Assistant. Only available when `HASS_TOKEN` is set. |
| `image_gen` | `image_generate` | Text-to-image generation via FAL.ai. |
| `memory` | `memory` | Persistent cross-session memory management. |
| `messaging` | `send_message` | Send messages to other platforms (Telegram, Discord, etc.) from within a session. |
| `moa` | `mixture_of_agents` | Multi-model consensus via Mixture of Agents. |
| `rl` | `rl_check_status`, `rl_edit_config`, `rl_get_current_config`, `rl_get_results`, `rl_list_environments`, `rl_list_runs`, `rl_select_environment`, `rl_start_training`, `rl_stop_training`, `rl_test_inference` | RL training environment management (Atropos). |
| `search` | `web_search` | Web search only (without extract). |
| `session_search` | `session_search` | Search past conversation sessions. |
| `skills` | `skill_manage`, `skill_view`, `skills_list` | Skill CRUD and browsing. |
| `terminal` | `process`, `terminal` | Shell command execution and background process management. |
| `todo` | `todo` | Task list management within a session. |
| `tts` | `text_to_speech` | Text-to-speech audio generation. |
| `vision` | `vision_analyze` | Image analysis via vision-capable models. |
| `web` | `web_extract`, `web_search` | Web search and page content extraction. |

## Composite Toolsets

These expand to multiple core toolsets, providing a convenient shorthand for common scenarios:

| Toolset | Expands to | Use case |
|---------|-----------|----------|
| `debugging` | `patch`, `process`, `read_file`, `search_files`, `terminal`, `web_extract`, `web_search`, `write_file` | Debug sessions — file access, terminal, and web research without browser or delegation overhead. |
| `safe` | `image_generate`, `vision_analyze`, `web_extract`, `web_search` | Read-only research and media generation. No file writes, no terminal access, no code execution. Good for untrusted or constrained environments. |

## Platform Toolsets

Platform toolsets define the complete tool configuration for a deployment target. Most messaging platforms use the same set as `birkin-cli`:

| Toolset | Differences from `birkin-cli` |
|---------|-------------------------------|
| `birkin-cli` | Full toolset — all 36 tools including `clarify`. The default for interactive CLI sessions. |
| `birkin-acp` | Drops `clarify`, `cronjob`, `image_generate`, `send_message`, `text_to_speech`, homeassistant tools. Focused on coding tasks in IDE context. |
| `birkin-api-server` | Drops `clarify`, `send_message`, and `text_to_speech`. Adds everything else — suitable for programmatic access where user interaction isn't possible. |
| `birkin-telegram` | Same as `birkin-cli`. |
| `birkin-discord` | Same as `birkin-cli`. |
| `birkin-slack` | Same as `birkin-cli`. |
| `birkin-whatsapp` | Same as `birkin-cli`. |
| `birkin-signal` | Same as `birkin-cli`. |
| `birkin-matrix` | Same as `birkin-cli`. |
| `birkin-mattermost` | Same as `birkin-cli`. |
| `birkin-email` | Same as `birkin-cli`. |
| `birkin-sms` | Same as `birkin-cli`. |
| `birkin-dingtalk` | Same as `birkin-cli`. |
| `birkin-feishu` | Same as `birkin-cli`. |
| `birkin-wecom` | Same as `birkin-cli`. |
| `birkin-wecom-callback` | WeCom callback toolset — enterprise self-built app messaging (full access). |
| `birkin-weixin` | Same as `birkin-cli`. |
| `birkin-bluebubbles` | Same as `birkin-cli`. |
| `birkin-qqbot` | Same as `birkin-cli`. |
| `birkin-homeassistant` | Same as `birkin-cli`. |
| `birkin-webhook` | Same as `birkin-cli`. |
| `birkin-gateway` | Union of all messaging platform toolsets. Used internally when the gateway needs the broadest possible tool set. |

## Dynamic Toolsets

### MCP server toolsets

Each configured MCP server generates a `mcp-<server>` toolset at runtime. For example, if you configure a `github` MCP server, a `mcp-github` toolset is created containing all tools that server exposes.

```yaml
# config.yaml
mcp:
  servers:
    github:
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
```

This creates a `mcp-github` toolset you can reference in `--toolsets` or platform configs.

### Plugin toolsets

Plugins can register their own toolsets via `ctx.register_tool()` during plugin initialization. These appear alongside built-in toolsets and can be enabled/disabled the same way.

### Custom toolsets

Define custom toolsets in `config.yaml` to create project-specific bundles:

```yaml
toolsets:
  - birkin-cli
custom_toolsets:
  data-science:
    - file
    - terminal
    - code_execution
    - web
    - vision
```

### Wildcards

- `all` or `*` — expands to every registered toolset (built-in + dynamic + plugin)

## Relationship to `birkin tools`

The `birkin tools` command provides a curses-based UI for toggling individual tools on or off per platform. This operates at the tool level (finer than toolsets) and persists to `config.yaml`. Disabled tools are filtered out even if their toolset is enabled.

See also: [Tools Reference](./tools-reference.md) for the complete list of individual tools and their parameters.
