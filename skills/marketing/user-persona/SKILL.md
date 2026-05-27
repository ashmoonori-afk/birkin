---
name: user-persona
description: "Build a grounded persona: goals, pains, triggers—sourced, not invented."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [marketing, personas, research, strategy]
---

# User Persona

Build a detailed customer persona grounded in real data: interview insights, surveys, or product analytics. Never invent demographics, goals, or pain points.

## When to Use

- You need to align marketing or product decisions on a specific customer segment.
- Building messaging or positioning for a new product or market.
- Documenting the core customer your sales/product team should target.

## When NOT to Use

- Competitive analysis or market sizing (use competitive analysis skill instead).
- Ad-hoc messaging; persona is most useful as a living reference document.

## Always establish first

**Data sources**: interviews (how many? who?), surveys, product usage data, or existing customer research. If no primary data exists, state that explicitly and use secondary sources only.

## Procedure

1. Identify the key customer segment you're building for.
2. Gather **primary data** using `memory_search` or `web_fetch` (customer interviews, support tickets, survey results).
3. Document:
   - **Profile**: role, industry, company size, years in role.
   - **Goals**: what they're trying to achieve (business or personal).
   - **Pain points**: specific frustrations, time sinks, budget constraints.
   - **Triggers**: what prompts them to search for a solution? (e.g., new initiative, tool failure, hiring).
   - **Objections**: common reasons they hesitate to buy.
   - **Success metrics**: how they measure win.
4. Quote real customer language where possible (interviews, reviews).
5. Note data gaps and assumptions explicitly.

## Output

- 1-page persona profile with above sections.
- Data source attribution for each claim.
- List of 3–5 validated interview or research sources.
- Explicitly mark inferred vs. confirmed insights.
