---
name: naming
description: "Generate and evaluate names for products, features, variables, or companies."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [creative, naming, branding]
---

# Naming

Produce a short list of memorable, distinctive names that fit the thing being
named and pass practical checks (availability, pronunciation, clarity).

## When to Use

- Naming a new product, feature, or service.
- Searching for better variable or function names in code.
- Need a brand name or domain name for a project or company.

## When NOT to Use

- Renaming is low priority and can wait (name it later, ship now).
- Need marketing positioning (use brainstorming skill instead).

## Procedure

1. **Define constraints**: What is it? Who uses it? Tone (playful, serious, technical)?
2. **Identify naming levers**: acronyms, metaphors, wordplay, invented words, descriptive.
3. **Generate 20–30 candidates** across different styles (alliterative, short, memorable, punny).
4. **Filter** for pronunciation clarity, no negative connotations, and reasonably unique.
5. **Check practical viability**: domain availability, trademark conflicts, length.
6. **Rank** the top 5–10 by memorability, fit, and distinctiveness.
7. Call `write_file` to save as naming-candidates.md with criteria and rationale.

## Output

- Markdown file with naming approach, candidate list, and top 5–10 ranked names.
- Each top candidate includes brief justification (why it works).
- Ready to test with users or stakeholders.
