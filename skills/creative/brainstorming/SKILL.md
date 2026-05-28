---
name: brainstorming
description: "Generate, cluster, and converge on ideas through structured divergence."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [creative, ideation, problem-solving]
---

# Brainstorming

Move from a vague problem or goal into a set of ranked, actionable ideas using
a proven diverge-then-converge pattern that avoids groupthink.

## When to Use

- Stuck on a feature, design, naming, or strategy challenge.
- Need multiple perspectives before committing to one direction.
- Want to explore the solution space broadly before narrowing.

## When NOT to Use

- Problem is already well-defined and only one solution fits (just build it).
- You need expert judgment, not raw ideas (hire or consult; don't brainstorm).

## Procedure

1. **Frame the challenge** in one question (e.g., "How might we reduce signup friction?").
2. **Diverge**: Generate 15–20 ideas without filtering; include wild and obvious ones.
3. **Cluster**: Group similar ideas into 3–5 themes (e.g., "remove fields," "simplify flow").
4. **Evaluate each cluster** on feasibility, impact, and novelty using a simple matrix.
5. **Converge**: Pick the top 2–3 ideas most likely to work or most interesting.
6. **Document** themes, top ideas, and the reasoning in a markdown file.
7. Call `write_file` to save as brainstorm-output.md.

## Output

- Markdown file with divergence list, clusters, evaluation matrix, and ranked ideas.
- Includes brief rationale for top picks.
- Ready for team discussion or next-phase planning.
