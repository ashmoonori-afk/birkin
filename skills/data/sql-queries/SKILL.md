---
name: sql-queries
description: "Write and optimize SQL: correct joins, indexes, avoid N+1, verify execution."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [data, sql, performance]
---

# SQL Queries

Write correct and performant SQL: use proper joins, add indexes where needed,
avoid N+1 queries, and verify results match intent.

## When to Use

- When writing or reviewing database queries.
- Before deploying queries that touch large tables or run frequently.
- When query performance is suspected to be slow.

## When NOT to Use

- For ORM-generated queries without explicit inspection (read the generated SQL first).

## Procedure

1. **Logic Check** — verify joins (INNER/LEFT/RIGHT) match the intent. Trace each
   column to its source table. Check WHERE clauses filter correctly.
2. **Indexes** — identify filters and sorts in WHERE/ORDER BY. Flag columns that
   should be indexed for performance; note existing indexes via run_shell queries.
3. **N+1 Detection** — look for loops that query per row. Use JOIN or IN clause
   instead; verify with EXPLAIN PLAN.
4. **Execution** — run_shell to test on real data (staging/test only). Check row
   counts, execution time, and plan for anomalies.
5. **Edge Cases** — test with empty sets, duplicates, nulls. Verify aggregates
   and GROUP BY handle these correctly.

## Output

- Corrected query with comments explaining joins and filters.
- Index recommendations and rationale.
- EXPLAIN PLAN output and performance notes.
- Test results: row counts and sample output.
