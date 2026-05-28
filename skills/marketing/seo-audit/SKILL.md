---
name: seo-audit
description: "Audit a page for on-page SEO: structure, metadata, intent alignment."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [marketing, seo, audit, content]
---

# SEO Audit

Assess a page's on-page SEO health: HTML structure, metadata completeness, keyword intent alignment, and technical factors that affect discoverability.

## When to Use

- A page is not ranking for intended keywords.
- You need to identify quick SEO wins before content rewrites.
- Metadata, headings, or internal links need improvement.

## When NOT to Use

- Diagnosing backlink or domain authority issues (use link analysis tools).
- Site-wide technical SEO (crawl errors, indexation); audit individual pages instead.

## Procedure

1. Fetch the page with `web_fetch`.
2. Extract and check:
   - Title tag (50–60 chars, includes primary keyword).
   - Meta description (150–160 chars, compelling, includes keyword).
   - H1 (one only; matches page intent).
   - H2–H3 structure (logical flow; keyword variants where natural).
   - Open Graph / JSON-LD tags (complete for sharing/rich snippets).
3. Identify primary keyword intent (informational, transactional, navigational).
4. Flag missing alt text, excessive ads, or poor readability (short paragraphs, bullet points).
5. Note internal linking opportunities.
6. List quick wins and structural gaps.

## Output

- Current state: title, description, H1, keyword alignment.
- Gaps: missing tags, thin structure, intent mismatch.
- Quick wins: title rewording, metadata updates, heading reorganization.
- Assumptions and sources where data is inferred.
