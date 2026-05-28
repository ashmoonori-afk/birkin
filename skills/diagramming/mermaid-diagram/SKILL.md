---
name: mermaid-diagram
description: "Generate Mermaid diagrams (flowchart, sequence, ER, state) from description."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [diagramming, documentation, visualization]
---

# Mermaid Diagram

Create a visual diagram (flowchart, sequence, entity-relationship, state machine)
from a verbal description and save it as Mermaid markdown so it renders in docs.

## When to Use

- Document a process flow, workflow, or decision tree.
- Show system architecture or component interactions.
- Illustrate database schema, API flow, or state transitions.
- Need a diagram that integrates with version-controlled markdown.

## When NOT to Use

- Complex hand-drawn visuals or branding assets (use design tool).
- Simple lists or text outlines (Mermaid adds no value).

## Procedure

1. **Choose diagram type**: flowchart (processes), sequence (interactions), ER (schema), state (state machine).
2. **Map the structure**: identify nodes, edges, and relationships from the description.
3. **Write Mermaid syntax** following the language spec (graph TD for flowchart, etc.).
4. **Validate** the syntax (mention if uncertain; Mermaid has strict grammar).
5. **Embed in markdown** with triple backticks and language tag: ` ```mermaid ... ``` `.
6. Call `write_file` to save as diagram.md or append to existing docs.

## Output

- Markdown file (.md) containing valid Mermaid code block.
- Can be viewed in GitHub, GitLab, Notion, and most markdown viewers.
- Ready to commit and share; no additional rendering tools needed.
