---
name: daily-digest
description: "Produce a concise daily digest of changes, open items, and suggested next actions."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [productivity, digest, nightly]
---

# Daily Digest

Summarize the recent day for the user: what changed, what is pending, and what
to do next. Well-suited to a morning cron job proposed by the nightly routine.

## When to Use

- The nightly routine or a cron job asks for a daily/standup summary.
- The user asks "what happened" or "what should I do today".

## When NOT to Use

- There is no recent activity to summarize.

## Procedure

1. Gather inputs: recent conversations, changed files (`list_files`, mtimes),
   pending approvals, and relevant memory notes (`memory_search`).
2. Group into: **Done**, **In progress**, **Blocked / needs decision**.
3. Derive **Top 3 next actions**, ordered by impact, each with a clear owner.
4. Keep it skimmable: short bullets, no filler.

## Output

```
# Digest — <date>
Done: …
In progress: …
Needs your decision: …
Top 3 next: 1) … 2) … 3) …
```
