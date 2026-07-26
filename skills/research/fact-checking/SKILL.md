---
name: fact-checking
description: "Verify a claim against 2+ primary sources via web_fetch."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [research, verification, fact-check]
---

# Fact Checking

Validate a specific claim by fetching and cross-checking 2 or more authoritative
sources. Output a clear verdict with evidence.

## When to Use

- A user or document makes a specific, checkable claim.
- You need to confirm or refute before relying on the claim for a decision.
- The claim is surprising or critical to act on.

## When NOT to Use

- The claim is opinion or subjective judgment.
- Primary sources are unavailable or behind paywalls.
- The claim is already verified in memory.

## Procedure

1. Restate the claim precisely (e.g., "X released product Y on date Z").
2. Identify 2–3 authoritative primary sources (official websites, academic
   databases, regulatory filings, established news outlets).
3. For each source, `web_search` for it if you do not already have the URL,
   then `web_fetch` the page and extract the relevant fact.
4. Compare findings: do they agree, conflict, or remain unclear?
5. If conflicting, fetch a third source or note the discrepancy and its possible
   causes.
6. Output:
   - **Claim** (the original statement)
   - **Verdict** (Confirmed / Refuted / Uncertain with likelihood)
   - **Evidence** (bullets for each source, URL, direct quote)
   - **Confidence** (high/medium/low, based on source authority and consistency)
7. Save verdict to memory with `memory_write_note` for future reference.

## Output

- A short, decisive report suitable for quick review or escalation.
- Direct quotes from sources or explanations of what was found and not found.
- Clear confidence level and reasoning.
