---
name: mcp-usage
description: "When and how to use MCP servers/tools effectively in agent workflows."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [knowledge, mcp, tools, integration]
---

# MCP Usage

Understand when to invoke MCP servers and tools, how to compose them into workflows, and how to handle errors or tool limitations.

## When to Use

- You need to integrate external data sources or APIs into an agent workflow.
- Building a multi-step process that requires reading files, querying APIs, or writing results.
- Automating tasks that would otherwise require manual tool switching.

## When NOT to Use

- Simple queries that don't require external data access.
- Tools that are not yet exposed as MCP servers (confirm via `load_skill` or documentation).

## MCP Concepts

1. **MCP Server**: A service that exposes tools and resources (e.g., file access, API calls, database queries).
2. **Tool**: A callable function (e.g., `read_file`, `web_fetch`, `run_shell`).
3. **Resource**: Static or queryable data the server provides (e.g., environment variables, knowledge bases).

## Procedure

1. **Identify the task**: what external resource or action do you need?
2. **Load the skill** corresponding to that MCP (e.g., `load_skill("mcp-usage")` for guidance).
3. **Check available tools**: use `memory_search` to list tools the MCP exposes.
4. **Compose the workflow**: chain tool calls in logical order (fetch → parse → write, etc.).
5. **Handle errors**: wrap calls with error checks; fall back gracefully if a tool fails.
6. **Log results**: use `memory_write_note` to track what succeeded and what didn't.

## Common MCP Workflows

- **Read → Transform → Write**: fetch data, process, save results.
- **Query → Fetch → Compose**: search knowledge base, fetch context, synthesize response.
- **Poll → Aggregate → Report**: check multiple sources, combine results, summarize findings.

## Output

- Workflow diagram or step-by-step list.
- Tool calls in pseudocode or actual code.
- Error-handling logic (what to do if a tool fails).
- Performance notes (tool latency, rate limits, costs).
