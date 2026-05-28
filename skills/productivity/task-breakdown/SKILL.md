---
name: task-breakdown
description: "Decompose a goal into ordered, owned, measurable tasks for execution."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [productivity, planning, execution]
---

# Task Breakdown

Turn a goal or epic into an ordered list of concrete tasks, each with a clear owner,
success criteria, and dependencies. Ensures nothing falls through cracks.

## When to Use

- A user states a goal but it is too large to execute immediately.
- Planning a feature, sprint, or initiative.
- After a brainstorm or strategy session.

## When NOT to Use

- The goal is already broken into tasks and assigned.
- The goal is too vague to decompose (clarify first).

## Procedure

1. Ask for or clarify: the goal, success criteria, constraints, timeline, and
   available people.
2. Identify phases and dependencies using `memory_write_note` to capture
   assumptions.
3. For each phase, create tasks:
   - Title: clear, action-oriented (verb + object).
   - Owner: a real person or role.
   - Success criteria: measurable; how we know it is done.
   - Estimated effort: t-shirt size (S/M/L) or hours.
   - Blocked by: list prior tasks.
4. Validate: no task spans multiple people or open-ended scope.
5. Output as an ordered list with owners and blockers visible.

## Output

```
# Breakdown — <goal>
Phase 1: <name>
  Task 1.1: <title>
    Owner: <person>
    Effort: M | Done when: <criteria>
    Blocked by: none

  Task 1.2: <title>
    Owner: <person>
    Effort: L | Done when: <criteria>
    Blocked by: Task 1.1
```
