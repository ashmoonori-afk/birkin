---
name: deep-research
description: "Multi-source investigation: decompose question, spawn subagents, synthesize sources into a structured, cited report artifact (Markdown file)."
version: 1.1.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [research, multi-source, synthesis]
---

# Deep Research

Conduct comprehensive investigation on a complex topic by decomposing it
into sub-questions, delegating research to subagents, and synthesizing findings
into a coherent, sourced report.

## When to Use

- The question requires investigation across multiple domains or sources.
- You need to compare perspectives, products, or findings.
- The answer is too large or complex for a single agent to handle efficiently.

## When NOT to Use

- The answer is already available in memory or workspace.
- The question is simple and requires only 1–2 sources.
- Time is critical and parallelization overhead is unaffordable.

## Procedure

1. Parse the user's question and identify 3–5 independent sub-questions or
   research angles (e.g., market size, competitor offerings, regulatory status).
2. For each sub-question, spawn a `spawn_subagent` with the web-research skill.
   Provide explicit scoping: what to find, which sources to prefer, what NOT to
   investigate.
3. Collect all subagent reports as they complete.
4. Synthesize across reports: reconcile conflicts, identify themes, note gaps.
5. Produce a structured report with:
   - **Objective** (what was investigated)
   - **Key Findings** (bullets, each sourced with an inline URL)
   - **Interpretation** (what the findings mean)
   - **Open Questions** (gaps not yet answered)
   - **Recommended Next Steps** (how to close gaps)
   - a **comparison table** when contrasting options/products/perspectives
     (one row per option, columns = the dimensions compared), and — when
     relationships matter — a small **```mermaid```** diagram (flow/mindmap).
   - a **Sources** list at the end (every URL cited above, deduplicated).
6. **Write the report as a file artifact** to `~/.birkin/research/<slug>.md`
   (slug = kebab-case of the question) with the write tool — a standalone,
   shareable Markdown report (this is the "deep research → report" deliverable).
   Return its path. Inline every claim's source; do NOT include a claim you
   can't cite (drop it).
7. Save a short synthesis to memory with `memory_write_note`, linking the report
   file and the key sources, so the finding is recalled later.

## Output

- A standalone **Markdown report file** at `~/.birkin/research/<slug>.md`:
  Objective → Key Findings (cited) → Interpretation → comparison table /
  diagram where useful → Open Questions → Recommended Next Steps → Sources.
- The report **path**, returned to the user (open/convert/share as-is).
- A linked memory note for future recall. Every claim traces to a URL; conflicts
  and gaps are called out explicitly (no fabricated certainty).
