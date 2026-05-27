---
name: semantic-memory
description: "Maintain the Obsidian memory vault well: when to write, classify, and link notes."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [memory, obsidian, knowledge]
---

# Semantic Memory (Obsidian vault)

birkin's memory is an Obsidian vault — markdown notes with frontmatter and
`[[wikilinks]]`. The principle is **compile over retrieve**: distill knowledge
into linked notes rather than dumping raw text.

## When to Use

- You learn a durable fact about the user, a project, a preference, or an entity.
- A decision is made that future sessions should respect.
- You can connect new information to an existing note.

## When NOT to Use

- Transient task state or secrets.
- Information that belongs in a skill (a reusable procedure) instead.

## How to write good notes

1. **One entity per note.** Title it by the entity (`FlowerPlus GTM`, not
   "today's chat").
2. **Classify** with `type`: `person | project | preference | fact | topic`.
3. **Link generously.** Pass `links` (or `memory_link`) so the graph connects —
   e.g. a project links to the people and topics it involves.
4. **Set confidence** honestly (0–1) and record the `source`.
5. **Update, don't duplicate.** Search first (`memory_search`); if a note
   exists, append/update it.

## Retrieval

- Use `memory_search` for keywords, then `memory_get_note` to read in full, and
  follow `[[wikilinks]]` to related notes.
