---
name: summarize-document
description: "Read a long doc and produce a faithful structured summary."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [data-science, documentation, summary]
---

# Summarize Document

Extract the essential structure and findings from a long document (report, paper,
proposal, code documentation) and produce a faithful, structured summary that
preserves key facts and reasoning.

## When to Use

- A user needs to understand a long document without reading the full text.
- Multiple documents need to be compared or synthesized.
- A document must be reformatted or abstracted for a specific audience.

## When NOT to Use

- The document is already short or well-structured.
- Only trivial facts are needed (skim the original instead).
- The document contains highly proprietary or sensitive information that should
  not be summarized.

## Procedure

1. Use `read_file` to load the document. If very large, read in sections (by
   page or chapter).
2. Identify structural elements:
   - Title, author, date
   - Executive summary (if present)
   - Main sections and subsections
   - Key arguments, evidence, conclusions
   - Recommendations or action items
3. Extract and organize findings by section:
   - Purpose / Problem Statement
   - Key Findings (with supporting data or reasoning)
   - Methodology or Approach (if applicable)
   - Assumptions and Limitations
   - Conclusions
   - Recommendations or Next Steps
4. Preserve factual accuracy: use direct quotes for critical claims, paraphrase
   supporting details. Do not fabricate facts.
5. Format the summary with:
   - **Overview** (one sentence: what is this document about?)
   - **Key Points** (5–10 bullets from main body)
   - **Findings** (organized by section or theme)
   - **Recommendations** (if present)
   - **Gaps or Limitations** (acknowledged by author or discovered)
6. Save summary to memory with `memory_write_note` and link to the original
   document.

## Output

- A structured summary (1–2 pages for a 10–50 page document).
- Preserves all critical facts, data points, and conclusions.
- Highlights open questions or limitations.
- Ready to share with stakeholders who need quick understanding.
