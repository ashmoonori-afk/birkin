---
name: web-research
description: "Research a topic on the web and synthesize a sourced, no-fabrication summary."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [research, web]
---

# Web Research

Investigate a question using `web_fetch` and produce a concise summary where
every claim is traceable to a source.

## When to Use

- The user asks about current facts, products, docs, or comparisons.
- You need external information before acting.

## When NOT to Use

- The answer is already in memory or the workspace (check first).
- The task is purely local (code, files).

## Procedure

1. Decompose the question into 2–4 concrete sub-questions.
2. For each, `web_fetch` an authoritative URL. Prefer primary sources
   (official docs, the vendor, the repo) over aggregators.
3. Extract only what the page actually says. **Do not fabricate**; if a fact
   cannot be sourced, drop the sentence.
4. Cross-check anything surprising against a second source.
5. Write: **conclusion**, then **key findings** as bullets, each with its URL.
6. If durable, save the synthesis to memory with `memory_write_note` and link
   related notes.

## Output

- A short answer first, then sourced bullets. Note open questions explicitly.
