# Native Application Security Boundary

Status: planned trust-boundary contract. Not yet implemented.

## Authority

Python alone decides:

- whether an operation is allowed
- whether approval or consent is required
- how an operation executes
- what audit and recovery state is recorded

SwiftUI never treats a toggle, focus state, menu command, notification tap, or local process state as authorization.

## Local authentication

Unix socket connections require private filesystem modes, same-user peer credentials, and a short-lived capability.

Private-loopback fallback requires Host and Origin pinning plus the capability from the first frame.

Session capabilities live in memory only. They expire on a sliding TTL, are renewed in-band, and are revoked on close, expiry, explicit revoke, or restart.

The private-loopback endpoint record contains a separate one-shot bootstrap secret in a `0600` file. It is consumed and rotated during hello and exchanged for the in-memory session capability. It is not a provider credential and cannot authorize product actions.

## Input bounds

The bridge rejects:

- oversized frames and payloads
- excessive nesting
- malformed UTF-8 and JSON
- unexpected keys
- invalid protocol transitions
- unsupported command handlers
- stale cursors and mutated command replays
- slow consumers and excess concurrency

## Persistence

The macOS application may persist presentation preferences only.

It must not persist:

- provider credentials
- protocol capabilities
- session or conversation content
- Working Memory or goals
- approvals or receipts
- Browser frames or profiles
- Computer Use artifacts
- Office document content
- pending command payloads

## Domain boundaries

### Browser Aside

Only private per-session profiles and audited control leases are exposed. Personal browser profiles are not supported.

### Computer Use

Status checks do not prompt. Foreground actions require a separate one-shot grant bound to the session, intent, prior receipt, and expiry.

### Office

Create and open operations use Python path identity, jail enforcement, provenance, and active-content consent.

### Terminal

The terminal process tree is owned by Python. Swift sends bounded input and signal commands and renders redacted output projections.

## Diagnostics

Diagnostics are bounded and redacted. They exclude tokens, raw request text, file contents, artifact bytes, terminal secret input, and tracebacks.

Raw private loopback does not use HTTP Host or Origin. Its one-shot `bootstrap_secret` authenticates only hello; the post-ready `session_capability` is separate. UDS peer credentials authenticate initial hello.

Command replay integrity stores a digest rather than plaintext canonical payloads. Public serializers remove integrity fields and raw terminal input before events, Activity, diagnostics, or exports leave Python.
