# Language Policy

Birkin separates human-facing copy from machine-facing contracts.

## Product surfaces

User-facing strings are Korean on Birkin-owned web, terminal, macOS, and
Windows surfaces. This includes:

- approvals, refusals, confirmations, and consequential-action warnings;
- errors, disabled-state explanations, and recovery actions;
- progress, retry, failover, and completion summaries;
- accessibility names and other text exposed by the product UI.

Decision and error copy should state the cause and the next action in one
bounded Korean message. Stable error codes may accompany that message, but
must not replace it. Raw exceptions, provider responses, protocol enums,
cursors, paths, process identifiers, and receipt JSON are diagnostic data and
must not be the primary user-facing explanation. Diagnostic details may appear
only in an explicitly disclosed, bounded detail surface.

## Rollout

This policy is the product-wide end state. Enforcement begins with approvals,
refusals, errors, recovery actions, progress, and completion results because
those surfaces determine whether a user can make and verify a consequential
decision. New or changed copy on those surfaces must comply now.

Legacy non-decision chrome and explicitly identified development-preview
diagnostics are migration work, not evidence that every Birkin surface is
already localized. They may remain while that migration is in progress, but
must not be copied into new decision surfaces or used as the primary
explanation for an action or failure.

## Machine contracts

Code, identifiers, protocol fields, structured event names, stable error
codes, logs, telemetry, and developer-facing diagnostics remain English.
Structured values such as `location`, `before`, `after`, `retryable`, and
receipt references remain language-neutral until the presentation layer
formats them.

The transport preserves bounded server messages for context, while each
presentation layer maps stable codes and typed fields to Korean copy. Unknown
codes use a bounded Korean fallback and retain the stable code for support.

## Documentation and tests

Engineering documents, code comments, and tests are written in English.
Korean product documentation and localization fixtures are exceptions because
their shipped content is Korean.

Tests should assert typed fields and stable codes first. Tests may assert exact
Korean text only when that text is a shipped resource or localization contract.
