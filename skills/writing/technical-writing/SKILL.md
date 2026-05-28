---
name: technical-writing
description: "Structure and draft clear technical documentation: READMEs, guides, API docs."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [writing, documentation, technical]
---

# Technical Writing

Turn complex technical concepts into clear, usable documentation that readers can
understand and act on without external help.

## When to Use

- Writing README, API docs, installation guides, or how-to tutorials.
- Restructuring confusing technical documentation for clarity.
- Need to explain system architecture, configuration, or workflows to engineers.

## When NOT to Use

- Marketing copy or user-facing content (use blog-post skill).
- Brief comments or inline code documentation (use code directly).
- One-off explanations in chat (only create skill if reusable).

## Procedure

1. Identify the **primary audience** (users, developers, DevOps) and their starting knowledge level.
2. Outline the logical flow: purpose → prerequisites → core steps → examples → troubleshooting.
3. Use descriptive headings, short paragraphs, code blocks with language markers, and lists.
4. Include one concrete **before/after** example showing both error and correct usage.
5. Add a **Troubleshooting** section with common errors and fixes.
6. Write in active voice; avoid jargon unless defined.
7. Call `write_file` to save the output as README.md, GUIDE.md, or similar.

## Output

- Markdown file (.md) with clear structure: headings, lists, code blocks.
- Estimated length: 500–2000 words depending on scope.
- Ready to commit and publish without edits.
