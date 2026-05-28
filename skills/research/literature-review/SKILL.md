---
name: literature-review
description: "Survey prior work on a topic, cluster findings, cite sources."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [research, literature, synthesis]
---

# Literature Review

Systematically survey published work on a research topic, organize findings
into clusters (themes), and produce a structured summary of the state of knowledge.

## When to Use

- You need to understand what has already been published or discovered.
- The task requires credibility via citations (academic, professional, legal).
- You need to position new work or ideas within existing context.

## When NOT to Use

- The question is purely operational or local (code, files, configuration).
- You have no access to academic databases or research platforms.
- The topic has very few published sources.

## Procedure

1. Define the topic precisely and list search keywords (e.g., "blockchain supply chain," "remote work productivity").
2. Use `web_fetch` to search academic databases, industry publications, or
   topic-specific sites (e.g., Google Scholar, arXiv, industry reports).
3. Collect 5–15 relevant sources. Prioritize peer-reviewed or authoritative
   publications.
4. For each source, extract:
   - Main finding or argument
   - Methodology (if applicable)
   - Publication date and author
   - URL or citation
5. Group sources by theme or sub-topic. Identify consensus and disagreement.
6. Write a synthesis report:
   - **Overview** (the landscape of research on this topic)
   - **Key Themes** (clusters of related work)
   - **Key Authors/Organizations** (influential contributors)
   - **Gaps** (what is not yet well researched)
   - **Full Bibliography** (complete citations and URLs)
7. Save synthesis to memory with `memory_write_note`.

## Output

- A structured literature map with 5–15 sources organized by theme.
- Bibliography with full citations and URLs.
- Explicit callout of gaps and directions for future research.
