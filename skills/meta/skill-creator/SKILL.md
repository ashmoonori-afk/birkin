---
name: skill-creator
description: "Author a new reusable SKILL.md skill from experience (self-improvement)."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [meta, skills, self-improvement]
---

# Skill Creator

Turn a repeatable procedure you just performed into a durable skill so it
persists for future sessions. This is the core of birkin's self-improvement.

## When to Use

- You solved a non-trivial task that is likely to recur.
- The user taught you a workflow, convention, or preference worth keeping.
- An existing skill is close but missing a step (use `improve_skill` instead).

## When NOT to Use

- One-off trivia or secrets (use memory notes, not skills).
- Something already covered by an existing skill — check the catalog first.

## How

1. Pick a short **kebab-case name** and a one-line **description** that says
   *when* to use it (this is what future-you sees in the index).
2. Write a concise markdown body with `When to Use`, `When NOT to Use`, and a
   numbered procedure. Keep it generalizable — no session-specific details.
3. Call `create_skill` with `name`, `description`, `body`, and `tags`.
4. Verify it appears via `load_skill <name>`.

## Quality bar

- A future agent can follow it without extra context.
- It states preconditions and failure modes.
- It is small and focused (one capability).
