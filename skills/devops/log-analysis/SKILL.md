---
name: log-analysis
description: "Find root causes in logs via grep patterns and systematic filtering."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [devops, debugging, logs]
---

# Log Analysis

Troubleshoot failures by searching logs for error patterns, timestamps, and context.
Use `run_shell` with grep, awk, and tail to isolate the issue.

## When to Use

- Application or service is failing and you have log access.
- Need to understand what happened between two timestamps.
- Searching for a specific error message across multiple logs.

## When NOT to Use

- No logs are available.
- The issue requires live debugging (attach a debugger instead).

## Procedure

1. Identify the log file(s) and source: application logs, system logs, container
   logs (`docker logs`), or remote service logs.
2. Narrow the time window: confirm when the failure occurred.
3. Use `run_shell` to search:
   - `grep ERROR <log>` — find error lines.
   - `grep -C5 "pattern" <log>` — show context around a match.
   - `tail -50 <log>` — show recent entries.
4. Look for the earliest error or anomaly; trace forward from there.
5. Extract stack traces, error codes, and timestamps.
6. Cross-reference with other logs (e.g., database, network, auth).
7. Document findings and the sequence of events.

## Output

```
Log source: <file|service>
Time window: <start> to <end>
Root cause: <identified issue>
Evidence:
  - Error: <message> at <timestamp>
  - Context: <surrounding log lines>
  - Related: <other log references>
```
