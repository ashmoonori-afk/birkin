---
name: ascii-art
description: "Create clean ASCII diagrams, banners, and simple visualizations as text."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [creative, diagramming, ascii]
---

# ASCII Art

Generate simple ASCII-based diagrams, flowcharts, or decorative text that render
cleanly in terminals, markdown, and plaintext contexts.

## When to Use

- Need a quick diagram for terminal output or plaintext docs.
- Creating visual separators, boxes, or banners for CLI tools or READMEs.
- Illustrating a simple process, table, or relationship in pure text.
- Want something that works everywhere without special rendering.

## When NOT to Use

- Complex multi-page diagrams (use Mermaid or design tools).
- Branding or polished graphics (use real design tools).
- Dense technical architecture (Mermaid or visio is clearer).

## Procedure

1. **Identify the visual goal**: banner, box, flowchart, table, simple tree, or banner.
2. **Choose ASCII elements**: lines (`|`, `-`, `/`, `\`), corners (`+`, `┌`, `└`, etc.), spaces.
3. **Sketch the layout**: rough proportions, alignment, and content placement.
4. **Build character by character** using monospace alignment; test in editor.
5. **Keep it simple**: 2–3 levels deep, max 20–30 lines (readability first).
6. **Add labels or legend** if needed to make purpose clear.
7. Call `write_file` to save as ascii-diagram.txt or append to markdown code block.

## Output

- Plain text file (.txt) or markdown code block.
- Renders identically in all terminals and plaintext viewers.
- Ready to copy into docs, README, or terminal output.
