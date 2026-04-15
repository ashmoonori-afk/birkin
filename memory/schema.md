# Birkin Memory Schema

This schema defines how the agent organizes its persistent knowledge.

## Categories
- entities/ — People, projects, tools, organizations
- concepts/ — Ideas, patterns, decisions, technical concepts
- sessions/ — Per-session summaries and context

## Files
- index.md — Content catalog listing all pages by category
- log.md — Append-only chronological record of operations

## Rules
- One topic per page
- Use [[wikilinks]] for cross-references
- Update index.md when adding or removing pages
- Append to log.md for every ingest or update operation
- Flag contradictions explicitly rather than silently overwriting
