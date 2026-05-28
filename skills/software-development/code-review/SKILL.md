---
name: code-review
description: "Review code for spaghetti, consistency, security, and progress against plan."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [software-development, review, quality]
---

# Code Review

Run a focused review after writing or changing code. Minimum dimensions:
spaghetti, consistency, security, and progress (the workspace's standard gate).

## When to Use

- Immediately after implementing or refactoring code.
- Before committing or proposing a change for execution.

## When NOT to Use

- For non-code deliverables (use a domain critique instead).

## Checklist

1. **Spaghetti** — functions < ~50 lines, files focused, nesting < 4 deep, clear
   names, no dead code.
2. **Consistency** — matches existing patterns, naming, and the stated design;
   no contradictory abstractions.
3. **Security** — no hardcoded secrets, inputs validated at boundaries, no
   injection/SSRF, errors don't leak sensitive data.
4. **Progress** — does it actually satisfy the plan/spec item? What's left?
5. **Errors** — failures handled explicitly; nothing silently swallowed.

## Output

- Findings grouped by severity (CRITICAL / HIGH / MEDIUM / LOW), each with file:line
  and a concrete fix. End with a go / no-go and remaining TODOs.
