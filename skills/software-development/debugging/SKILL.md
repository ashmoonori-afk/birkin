---
name: debugging
description: "Debug and repair failing programs through reproduction, hypotheses, regression proof, root-cause fixes, and real-surface QA. 디버깅 프로그램 버그 재현."
version: 2.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [software-development, debugging, programming, troubleshooting, 디버깅, 프로그램, 버그, 재현]
    provenance: birkin-original
    protocol: [reproduce, pin, hypothesize, experiment, red, root-cause, fix, verify, manual-qa, cleanup]
---

# Debugging

Repair the cause of a failing program, not the nearest symptom. Move from a
reproducible observation to distinguishing hypotheses, failing regression
proof, the smallest root fix, and evidence from the real user surface.

This is a Birkin-original programming workflow. It is not derived from the
Devkode.io frontend architecture checklist.

## When to Use

- A program crashes, hangs, returns the wrong result, or silently fails.
- A test, build, integration, browser flow, CLI, or service behaves
  unexpectedly.
- A bug is intermittent, environment-specific, or only appears in CI.
- 프로그램 버그 재현, 디버깅, 실패 원인 분석이 필요한 경우.

## When NOT to Use

- For architecture decisions without an observed failure.
- For speculative cleanup or unrelated refactoring.
- For performance work without a measured regression.

## Rules

- Read the relevant code and caller/dependency path before editing.
- Preserve exact inputs, environment, command, output, and expected behavior.
- Form at least three mutually distinguishing hypotheses for runtime bugs.
- Change one diagnostic variable at a time.
- Never hide a failure by suppressing diagnostics, weakening a test, or adding
  an unexplained retry.
- Do not use fixed sleeps for asynchronous tests; subscribe to the state or
  event being asserted and bound the wait.
- Remove temporary logging, files, servers, browser contexts, ports, and
  environment changes before declaring success.

## Protocol

### 1. Reproduce

Use `run_shell` or the actual application surface to make the failure happen
on demand. Capture:

- exact command, request, click path, or input;
- expected versus actual result;
- stack trace, status, logs, and environment versions;
- whether the failure is deterministic, intermittent, or environment-bound.

If it cannot be reproduced, collect the smallest additional evidence that
would distinguish the likely causes. Do not guess a fix.

### 2. Pin surrounding behavior

Before a refactor or risky fix, add a characterization test for behavior that
must remain unchanged. It must pass against the current code and cover the
same boundary the fix could disturb.

Skip characterization only when the failing regression test alone fully
defines the seam.

### 3. Form hypotheses

Write at least three candidate causes that predict different observations.
Include:

- the suspected boundary or state transition;
- evidence for and against;
- one experiment whose result would eliminate or strengthen it.

Rank them by explanatory power and test cost, not familiarity.

### 4. Run distinguishing experiments

Use `list_files`, `read_file`, logs, traces, debugger breakpoints, network
inspection, or narrow shell commands to test each hypothesis. Trace at least
one caller and one dependency beyond an apparently obvious failing line.

Record the observation and update the hypothesis table. Repeating the same
command without a new discriminator is not progress.

### 5. Capture RED

Add the cheapest faithful automated regression proof:

- unit test for isolated logic;
- integration test for wiring or persistence;
- end-to-end test for a boundary that mocks would erase;
- real-surface scenario when no reliable automated seam exists.

Run it before production code changes. It must fail for the expected behavior,
not from syntax, import, setup, or timing errors.

### 6. Establish the root cause

State the complete causal chain:

1. triggering input or state;
2. first incorrect transition;
3. why existing validation or tests allowed it;
4. resulting user-visible failure.

A stack-trace endpoint is evidence, not automatically the cause.

### 7. Apply the smallest fix

Change only the code required to break the causal chain. Preserve local style,
public contracts, and unrelated behavior. Do not bundle cleanup, speculative
fallbacks, broad abstractions, or silent exception handling.

### 8. Verify proportionally

Run:

- the regression proof until GREEN;
- static diagnostics for changed code;
- related tests and the affected entry point;
- the full build or suite when the change crosses domains.

Fix only failures caused by the change and identify pre-existing failures
separately.

### 9. Exercise the real surface

Use the repaired behavior the way a user does:

- CLI/TUI: `--help`, one successful case, one invalid input;
- HTTP/service: hit the live process and inspect status, headers, and body;
- web UI: use a real browser and inspect visible state plus console/network;
- library: import and execute a minimal driver.

Tests alone do not prove the user-facing failure is fixed.

### 10. Clean and report

Remove every debug-only artifact and verify teardown. Report:

- reproduction and RED evidence;
- confirmed root cause and eliminated hypotheses;
- minimal fix;
- GREEN checks and real-surface evidence;
- cleanup receipt;
- residual risks or checks that could not run.

## Output

Return a compact evidence ledger:

| Stage | Evidence |
|---|---|
| Reproduction | exact invocation and observed failure |
| Hypotheses | predictions, experiments, and eliminations |
| RED | failing test or real-surface artifact |
| Root cause | causal chain and affected boundary |
| Fix | smallest changed behavior |
| GREEN | diagnostics, tests, and entry-point result |
| Manual QA | real-surface action and binary observable |
| Cleanup | terminated resources and removed artifacts |

