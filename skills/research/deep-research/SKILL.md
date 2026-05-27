---
name: deep-research
description: "Multi-source investigation: decompose question, spawn subagents, synthesize sourced report."
version: 1.0.0
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
   - **Key Findings** (bullets, each sourced with URL)
   - **Interpretation** (what the findings mean)
   - **Open Questions** (gaps not yet answered)
   - **Recommended Next Steps** (how to close gaps)
6. Save the synthesis to memory with `memory_write_note` and link to original
   subagent reports and sources.

## Output

- A comprehensive report organized by sub-question, with all claims traced to
  sources (URLs).
- Explicit callout of open questions and conflicting findings.
- Ready-to-share summary for stakeholders or decision-makers.
