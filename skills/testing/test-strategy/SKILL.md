---
name: test-strategy
description: "Determine what tests to write and how: unit, integration, e2e coverage."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [testing, strategy, coverage]
---

# Test Strategy

Decide what to test, at what level, and when. Balance speed (unit) with
confidence (integration/e2e) to reach 80%+ coverage efficiently.

## When to Use

- Before writing new tests for a feature.
- When deciding whether a component needs e2e, integration, or unit tests.
- To prioritize testing effort on high-risk paths.

## When NOT to Use

- When implementation is not yet written (write tests first via TDD workflow).

## Procedure

1. **Map the Feature** — list user flows, critical paths, and edge cases using
   read_file on specs/requirements.
2. **Identify Layers** — determine which parts are business logic (unit), which
   touch external systems (integration), which are user-visible (e2e).
3. **Set Coverage Goal** — aim for 80%+. Unit tests cover most branches; integration
   tests cover API/database flows; e2e tests cover critical journeys.
4. **Prioritize** — unit tests first (fast), then integration for boundary
   conditions, then e2e for top conversion paths.
5. **Check for Gaps** — review existing tests with read_file; add only missing
   coverage, not duplicate tests.

## Output

- Test breakdown by layer (unit: N%, integration: N%, e2e: N%).
- List of test cases per layer with coverage estimates.
- Implementation order and priority.
