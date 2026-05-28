---
name: a11y-audit
description: "Audit UI/content for WCAG basics: semantics, contrast, keyboard, alt text."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [accessibility, audit, wcag]
---

# Accessibility Audit

Audit a page or component for WCAG 2.1 Level AA basics: semantic HTML, color
contrast, keyboard navigation, alt text for images, and form labeling.

## When to Use

- Before launching a new page or feature.
- When redesigning existing UI.
- As part of quality gate for public-facing interfaces.

## When NOT to Use

- For internal admin tools where accessibility is lower priority (document that decision).

## Procedure

1. **Semantics** — use read_file on HTML. Check for proper heading hierarchy (h1,
   h2, h3), <button> for buttons, <a> for links, <label> for form inputs.
2. **Contrast** — visually inspect or use a tool: foreground/background must have
   4.5:1 ratio for normal text, 3:1 for large text.
3. **Keyboard** — manually tab through the interface. Verify focus is visible,
   tab order is logical, and all interactive elements are reachable.
4. **Alt Text** — every <img> needs alt="description" (or alt="" if decorative).
   Check that descriptions are meaningful, not just filename.
5. **Form Labels** — <label for="id"> must match input id. If label is not present,
   use aria-label or aria-labelledby.
6. **ARIA** — add aria-live, aria-hidden, role, aria-label only when needed; don't
   over-use. Semantic HTML is preferred.

## Output

- List of issues by category (Semantics / Contrast / Keyboard / Alt Text / Labels).
- Each issue includes location (page/component path) and fix.
- Compliance level (WCAG 2.1 AA met, or gaps to close).
