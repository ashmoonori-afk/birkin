---
name: planning
description: "Create a phased plan with milestones, risks, and success criteria."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [productivity, planning, strategy]
---

# Planning

Build a roadmap for a project or initiative: phases, milestones, dependencies, risks,
and how to measure success. Clarifies scope and surface blockers early.

## When to Use

- User has an initiative and needs a structured plan.
- Preparing to brief stakeholders or align a team.
- Planning a feature, launch, or organizational change.

## When NOT to Use

- The plan already exists and is current.
- The initiative is too immature to plan (do discovery first).

## Procedure

1. Clarify: goal, constraints (timeline, budget, people), and success metrics.
2. Define phases, in order, with clear entry/exit criteria.
3. For each phase, list key milestones and deliverables.
4. Identify dependencies between phases and external blockers.
5. Use `memory_write_note` to document assumptions and decisions.
6. Call out risks and mitigation for each phase.
7. Validate timeline and resource allocation are realistic.
8. Output as a structured roadmap with phases, dates, and owners.

## Output

```
# <Initiative> Plan

Success metrics: …
Timeline: <start> to <end>

Phase 1: <name> (Week 1–3)
  Milestone: <deliver what>
  Owner: <person/team>
  Risks: 1) … 2) …
  Exit criteria: <how we know it is done>

Phase 2: <name> (Week 4–6)
  …
```
