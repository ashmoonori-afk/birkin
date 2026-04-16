---
name: code-review
description: Review code for quality, security, and best practice issues
version: "0.1.0"
triggers:
  - review
  - code review
  - PR review
tools:
  - review_code
---

## Instructions

When the user asks for a code review, use the `review_code` tool to analyze
the provided code. Focus on:

1. **Security** — injection, hardcoded secrets, unsafe operations
2. **Quality** — naming, complexity, dead code, duplication
3. **Best practices** — error handling, type safety, documentation
4. **Performance** — unnecessary allocations, N+1 queries, blocking I/O

Return a structured review with severity levels: CRITICAL, HIGH, MEDIUM, LOW.
