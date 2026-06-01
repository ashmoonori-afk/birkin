---
name: codex-image-gen
description: "Generate raster images (PNG) from a text prompt the FREE way — reuse a signed-in ChatGPT/Codex OAuth session (gpt-image-2, NO OPENAI_API_KEY) via the god-tibo-imagen CLI or an inherited image tool; save the file and return its path. Networked generation follows birkin approval rules."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [creative, image-generation, codex, oauth, gpt-image]
    entrypoint: "god-tibo-imagen `gti` CLI (Codex OAuth) · or an inherited image_generate tool / image MCP"
---

# Codex Image Generation — gpt-image-2 via OAuth, no API key

Turn a text prompt into a real **PNG image for free**, by reusing a signed-in
**ChatGPT/Codex OAuth** session instead of a paid `OPENAI_API_KEY` — the same
login that powers the `codex-cli` backend. This is the free/OAuth ethos applied
to images, the capability requested in
[openclaw#70703](https://github.com/openclaw/openclaw/issues/70703)
*("support gpt-image-2 in image_generate via Codex OAuth")*.

**birkin has no native image-generation tool today** (the in-loop registry is
`files`·`shell`·`web`·`skills`·`memory`·`subagent`; the only built-in visual
output is text `ascii-art`). So this skill reaches an image capability that lives
**outside** birkin's own tools — preferably the **`god-tibo-imagen` CLI** (a real
installable tool that does the Codex-OAuth call), or an inherited image tool —
and runs it under birkin's approval rules.

## When to Use

- The user wants a real **raster image** (photo/illustration/icon/sticker, PNG)
  from a prompt — not an ASCII diagram.
- A signed-in **ChatGPT/Codex OAuth** session exists (or can be), so the free
  `gpt-image-2` path is reachable.

## When NOT to Use

- For plaintext diagrams/banners/boxes/flowcharts — use `ascii-art`.
- When **no image route is available** and the user won't sign in / install a
  tool — say so and stop. Do **not** fabricate an image or claim success.
- To spend money: a paid `OPENAI_API_KEY` (or other paid image key) is an
  **optional fallback only**, never the default.

## Requirements

1. **A signed-in ChatGPT/Codex OAuth session** for the free path — the local
   Codex login (`~/.codex/auth.json`). No `OPENAI_API_KEY` needed.
2. **A reachable image route** — one of: the `god-tibo-imagen` CLI installed
   (Route A), an inherited image MCP tool (Route B), or an OpenClaw-style
   `image_generate` tool in the current toolset (Route C).
3. **If none is available:** tell the user to either install `god-tibo-imagen`
   (`npm i -g god-tibo-imagen` or `pip install god-tibo-imagen`) and sign in to
   Codex, OR enable an image MCP / set a provider key — then stop. Don't guess.

## ⚠️ Caveat — unofficial backend

The free Codex-OAuth path (Route A, and the mechanism behind it) sends requests
to ChatGPT's **private, undocumented backend** (`https://chatgpt.com/backend-api/
codex/responses`). Per god-tibo-imagen's own warning it is *"not a supported
public API integration and relies on private behavior that may change anytime."*
A known transport bug (hermes issue #31335, v0.14.0) reports that backend may
**strip the `tools` array / ignore `tool_choice`**, so the call can fail
end-to-end. Treat success as best-effort: if it fails, report honestly and offer
a fallback — never fake an image.

## Procedure

Pick the **first available** route. Image generation is a **networked,
consequential** action: on the free sandboxed `claude-cli` path the allow-list is
`Read, Glob, Grep + mcp__birkin__*`, so you **cannot** shell out or make an HTTP
call in-loop — use an already-allow-listed/inherited tool, or `propose_action`
(`category: "shell"`, exact command) so the user approves it later via
`birkin review`. Never invent a flag/endpoint/model not in **Sources**.

### Route A — `god-tibo-imagen` (`gti`) CLI  *(recommended free path)*

A Node.js/Python CLI that sends the image request to Codex's ChatGPT-authenticated
backend, reusing `~/.codex/auth.json` — **no API key**, model `gpt-image-2`,
output PNG.

1. Ensure it is installed: `npm install -g god-tibo-imagen` (or
   `pip install god-tibo-imagen`), and the user is signed in to Codex.
2. Run (via an approved shell step — see the approval note above):
   ```
   gti --prompt "flat blue square app icon, minimal" --output ./out.png
   # options: --image ./reference.png   --size 1536x1024 | 1024x1024 | 1024x1536
   ```
3. Return the saved PNG path. (Under the sandboxed path, `propose_action` the
   exact `gti …` command instead of running it.)

### Route B — Inherited image MCP tool (if present)

1. Detect an image-generating MCP tool inherited from Claude Code
   (`birkin mcp list` / `/mcp`); birkin passes Claude Code's MCP servers through.
2. If present and allow-listed, call it by its **exact** tool name with the
   prompt and any documented size/format/background options.
3. Save the result and return the path.

### Route C — OpenClaw-style `image_generate` tool (if present)

1. If an `image_generate` tool is in the toolset, call it. With no per-call
   `model` it resolves a provider in order (primary → fallbacks → auth default)
   and auto-retries the next on failure.
2. **Free path:** leave `model` unset (or use `openai/gpt-image-2`) so a
   signed-in ChatGPT/Codex OAuth profile is used with no `OPENAI_API_KEY`
   (<https://docs.openclaw.ai/tools/image-generation>). Transparent backgrounds:
   `openai/gpt-image-1.5`. **Caveat:** a per-call `model` override uses **only**
   that provider and does **not** fall back — omit it unless you want exactly one.
3. Save the result and return the path.

### Underlying mechanism (for custom wiring only)

Routes A–C all resolve to the same thing: the **OpenAI/Codex Responses API**
built-in **`image_generation`** tool (model `gpt-image-2`), called with a
ChatGPT/Codex OAuth bearer token — **not** the `images.generate` REST endpoint
and **not** a `codex generate-image` CLI flag (no such flag exists in any source).
Endpoint `POST https://chatgpt.com/backend-api/codex/responses`; the payload sets
`tools: [{"type":"image_generation","model":"gpt-image-2",…,"output_format":"png"}]`
and streams base64 PNG via SSE. Prefer Route A (it implements exactly this) over
hand-rolling the HTTP call.

## Output

- One **PNG** saved to disk (e.g. `~/.birkin/images/<name>.png` or a cwd path).
- The **absolute file path**, returned to the user.
- A one-line note of **which route + model** was used (e.g. "Route A · gti ·
  gpt-image-2 via Codex OAuth"), so the result is reproducible.
- On failure: a clear **why** (not signed in / no route / queued for approval /
  unofficial-backend bug) and the next step — never a faked image.

## Notes

- **Free first, key optional.** Default to ChatGPT/Codex **OAuth** + `gpt-image-2`
  with no `OPENAI_API_KEY`. An API key is a fallback only; note that explicitly
  configuring `models.providers.openai` (a key / custom base URL) **opts back
  into paid direct OpenAI Images routing instead of OAuth**
  (<https://docs.openclaw.ai/tools/image-generation>).
- **Conservative beats clever:** if unsure the route works or is allowed in-loop,
  `propose_action` it for `birkin review` rather than forcing a networked call.

## Sources

- [openclaw#70703](https://github.com/openclaw/openclaw/issues/70703) — the
  feature request: gpt-image-2 in `image_generate` via Codex OAuth (no API key).
- [NomaDamas/god-tibo-imagen](https://github.com/NomaDamas/god-tibo-imagen) — the
  `gti` CLI/lib that performs the Codex-OAuth image call (reuses `~/.codex/auth.json`,
  `gpt-image-2`, PNG out); source of the unofficial-backend caveat.
- [OpenClaw image-generation docs](https://docs.openclaw.ai/tools/image-generation)
  — `image_generate` tool, OAuth routing, provider order.
- [hermes openai-codex image_gen plugin](https://raw.githubusercontent.com/NousResearch/hermes-agent/main/plugins/image_gen/openai-codex/__init__.py)
  — Responses `image_generation` tool, endpoint/model/payload; bug: hermes issue #31335.
- birkin house style + "no native image gen" audit: canonical tree
  (`skills/creative/ascii-art/SKILL.md`, `birkin/tools/`, `birkin/mcp_server.py`).
