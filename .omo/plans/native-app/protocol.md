# Birkin Local Native Protocol

Protocol name: `birkin-local-1`
Workspace protocol version source: `birkin.workspace.contracts.PROTOCOL_VERSION`

## 1. Goals

- local-private communication
- strict negotiation
- bounded memory and concurrency
- short-lived authentication
- canonical workspace commands and receipts
- replayable snapshots and events
- explicit disconnection and recovery
- no provider credentials or hidden execution data

## 2. Transport

### 2.1 Unix domain socket

Primary endpoint:

`$BIRKIN_HOME/native/run/<uid>.sock`

Requirements:

- parent directories mode `0700`
- socket mode `0600`
- path checked with `lstat`
- no symlink traversal
- reject paths exceeding the macOS `sun_path` bound before bind
- same effective user required through macOS peer credentials
- stale socket removed only after a failed connect probe under a lock
- a live endpoint is attached, never replaced

Authentication:

1. private directory and socket mode
2. same-user peer credential
3. short-lived protocol capability

### 2.2 Private-loopback fallback

Fallback is allowed only after a declared UDS failure or explicit diagnostic configuration.

Requirements:

- bind only `127.0.0.1`
- use an ephemeral port
- endpoint record mode `0600` with a dedicated one-shot bootstrap secret
- bootstrap secret is not a provider credential or session capability
- client reads it only at connect time and sends it in `hello`
- successful exchange consumes and rotates it, then returns the normal in-memory capability in `ready`
- pin Host and Origin
- never expose `0.0.0.0`
- never accept unauthenticated TCP

The UI visibly reports why fallback is active.

## 3. Frame

```text
uint32_be body_length
body_length bytes of UTF-8 JSON
```

Bounds:

| Item | Limit |
| --- | ---: |
| frame body | 262,144 bytes |
| workspace command payload | 65,536 bytes |
| JSON depth | 12 |
| in-flight client frames | 64 |
| in-flight commands | 8 |
| subscriptions | 32 |
| outbound event queue | 512 |
| partial-frame timeout | 5 seconds |
| socket unwritable timeout | 10 seconds |
| diagnostic entries | 200 |

The server checks the declared body length before allocating.

## 4. Envelope

```json
{
  "protocol": "birkin-local-1",
  "protocol_version": 1,
  "kind": "hello",
  "id": "01J...",
  "in_reply_to": null,
  "body": {}
}
```

Rules:

- exact top-level keys
- `id` is a bounded identifier unique per connection
- `in_reply_to` is required for direct responses
- every post-handshake frame carries the selected protocol version
- unknown kinds are rejected and journaled as bounded protocol diagnostics
- extra keys are rejected

Registered kinds are:

`hello`, `ready`, `subscribe`, `snapshot`, `event`, `surface_snapshot`, `surface_event`, `command`, `receipt`, `error`, `capability.renewed`, `stream.desynchronized`, `ping`, `pong`, and `goodbye`.

`capability.renewed` is server-originated and valid after `ready`. `stream.desynchronized` is server-originated and valid only for a subscribed connection.

## 5. Connection state machine

```text
accepted
  -> hello_required
  -> negotiated
  -> ready
  -> subscribed
  -> draining
  -> closed
```

Invalid transitions fail with `E_STATE`.

Only `hello` is valid before negotiation. Only `subscribe`, `ping`, and `goodbye` are valid before a session subscription.

## 6. Negotiation

### 6.1 Hello

```json
{
  "kind": "hello",
  "body": {
    "client": "birkin-macos",
    "client_version": "1.0.0",
    "client_build": "100",
    "supported_protocol_versions": [1],
    "surface": "macos",
    "view_id": "window-main",
    "bootstrap_secret": "<one-shot loopback secret or null on UDS>"
  }
}
```

The `macos` surface is an additive workspace contract value.

### 6.2 Ready

```json
{
  "kind": "ready",
  "body": {
    "protocol_version": 1,
    "server_version": "1.0.0",
    "instance_id": "uuid",
    "transport": "uds",
    "capability": {
      "token": "opaque",
      "expires_at": "2026-08-17T00:15:00Z",
      "ttl_seconds": 900,
      "hard_expires_at": "2026-08-17T08:00:00Z"
    },
    "limits": {
      "max_frame_bytes": 262144,
      "max_payload_bytes": 65536,
      "max_json_depth": 12,
      "max_inflight_commands": 8,
      "max_subscriptions": 32
    },
    "capabilities": {
      "commands": [],
      "workspace_panels": [],
      "surfaces": {},
      "features": {}
    }
  }
}
```

`commands` comes from registered handlers. It is not copied from the declared command-type list.

Version mismatch:

- return `E_PROTOCOL_VERSION`
- include client and server version sets
- do not downgrade
- close after the error

## 7. Capabilities

- token: `secrets.token_urlsafe(32)`
- normal TTL: 900 seconds
- sliding renewal on accepted authenticated frames
- hard ceiling: 8 hours per connection
- memory-only in Swift
- constant-time comparison
- scoped to instance, connection, client surface, and view identifier
- revoked on close, goodbye, bridge restart, explicit revoke, or expiry

Capability renewal:

- server sends `capability.renewed`
- client atomically swaps the in-memory token
- UI remains ready without a connection-state flicker
- a failed renewal triggers one full handshake

The local protocol capability does not authorize:

- approval answers
- Computer Use foreground retry
- Browser control handoff
- Office active-content consent
- policy changes

Those remain separate canonical decisions.

## 8. Workspace subscription

### 8.1 Subscribe

```json
{
  "kind": "subscribe",
  "body": {
    "session_id": "session-id",
    "after_cursor": 42,
    "capability": "opaque",
    "surfaces": {
      "browser": {"revision": 7},
      "computer_use": {"revision": 2},
      "office": {"revision": 4},
      "working_memory": {"revision": 12},
      "terminal": {"streams": {"term-id": 23}}
    }
  }
}
```

### 8.2 Snapshot

The workspace snapshot is the canonical `WorkspaceSnapshot` public JSON plus:

- `instance_id`
- negotiated capability metadata that is safe to disclose

The bridge does not re-derive workspace panel semantics.

### 8.3 Event

The event body is canonical `WorkspaceEvent` public JSON.

Requirements:

- strictly monotonic cursor
- exact session identity
- redacted bounded payload
- full replay when a gap is detected

## 9. Commands and receipts

### 9.1 Command

```json
{
  "kind": "command",
  "body": {
    "capability": "opaque",
    "command": {
      "protocol_version": 1,
      "command_id": "macos-01J...",
      "expected_cursor": 42,
      "type": "chat.send",
      "payload": {
        "text": "Hello"
      },
      "client_context": {
        "surface": "macos",
        "view_id": "window-main"
      }
    }
  }
}
```

The nested command is parsed unchanged by `WorkspaceCommand.parse`.

### 9.2 Receipt

```json
{
  "kind": "receipt",
  "body": {
    "command_id": "macos-01J...",
    "outcome": "accepted",
    "duplicate": false,
    "accepted_cursor": 43
  }
}
```

Fingerprints are never public.

Terminal success is determined only by later canonical completion or failure events.

### 9.3 Idempotency

- generate a command identifier once per user intent
- retain it across reconnect recovery
- same identifier and fingerprint returns the prior receipt
- same identifier and changed fingerprint returns `E_COMMAND_ID_CONFLICT`
- retrying after a canonical terminal failure creates a new identifier

### 9.4 Stale cursor

- `chat.interrupt`: refresh and retry once with the same intent identifier
- all other commands: refresh, preserve the draft, display inline conflict, require explicit re-submit
- never silently replay approval, config, checkpoint, terminal signal, Browser control, Computer Use, or Office consent actions

## 10. Surface projections

### 10.1 Surface snapshot

```json
{
  "kind": "surface_snapshot",
  "body": {
    "surface": "browser",
    "session_id": "session-id",
    "revision": 7,
    "payload": {}
  }
}
```

### 10.2 Surface event

```json
{
  "kind": "surface_event",
  "body": {
    "surface": "browser",
    "session_id": "session-id",
    "revision": 8,
    "event_type": "browser.frame.updated",
    "payload": {}
  }
}
```

Rules:

- surface names must be advertised
- revisions are monotonic per session and surface
- gaps trigger a full surface snapshot
- raw bytes, request text, provider data, tokens, and personal-profile data are forbidden

## 11. Terminal contract

Terminal commands are canonical workspace command additions with strict payloads.

### Terminal policy and actor

`terminal.create` carries `actor_kind: "native_human"`. Python evaluates canonical shell policy and, when required, creates a `shell` approval before returning a terminal access lease. The lease is bound to the session, actor, shell, cwd, and expiry. `terminal.input`, `terminal.resize`, `terminal.signal`, and `terminal.close` require the live lease in addition to the local connection capability.

### Create

```json
{
  "type": "terminal.create",
  "payload": {
    "actor_kind": "native_human",
    "cwd": "workspace-relative-path",
    "columns": 120,
    "rows": 40
  }
}
```

### Input

```json
{
  "type": "terminal.input",
  "payload": {
    "terminal_id": "term-id",
    "sequence": 3,
    "text": "pytest\n"
  }
}
```

### Resize

```json
{
  "type": "terminal.resize",
  "payload": {
    "terminal_id": "term-id",
    "columns": 160,
    "rows": 50
  }
}
```

### Signal

```json
{
  "type": "terminal.signal",
  "payload": {
    "terminal_id": "term-id",
    "signal": "interrupt"
  }
}
```

### Close

```json
{
  "type": "terminal.close",
  "payload": {
    "terminal_id": "term-id"
  }
}
```

Terminal output is a negotiated surface event with:

- terminal identifier
- monotonic output sequence
- encoding
- bounded data chunk
- stream kind

Sensitive input is never echoed into diagnostics or Activity.

## 12. Working Memory command

Working Memory mutation reuses the existing `memory.write` workspace command.

```json
{
  "type": "memory.write",
  "payload": {
    "op": "merge",
    "expected_revision": 12,
    "fields": {
      "constraints": ["..."],
      "decisions": ["..."]
    }
  }
}
```

Clear uses the same command with `{ "op": "clear", "expected_revision": 12 }`. Python validates the canonical field allowlist, rendered-size budget, revision, and policy before committing.

## 13. Attachments and imports

File bytes are not inlined.

Flow:

1. Swift receives a security-scoped drop or picker URL.
2. Swift sends an import intent through the authenticated bridge.
3. Python opens and copies through the jailed import service.
4. Python returns content hash, jailed URI, size, media type, and receipt.
5. Composer sends only the returned reference.

Limits, symlink behavior, active content, and path identity are enforced by Python.

## 14. Heartbeat and disconnect

- client sends `ping` every 15 seconds
- server replies `pong`
- two missed replies mark the client disconnected
- 45 seconds of peer silence closes the connection
- disconnect disables mutation immediately

Reconnect backoff:

`250ms, 500ms, 1s, 2s, 4s, 8s`, capped at 8 seconds with bounded jitter.

No retry budget expires while the app is open, but the state remains visibly disconnected.

## 15. Backpressure

When the outbound event queue reaches its limit:

1. stop normal delivery
2. send one `stream.desynchronized` protocol notice with the last delivered cursor
3. require resubscription

If the socket remains unwritable for ten seconds, close.

The journal remains durable. Events are never silently discarded.

Swift drains transport independently of rendering and coalesces assistant deltas only at the presentation layer.

## 16. Errors

| Code | Meaning | Retry |
| --- | --- | --- |
| `E_PROTOCOL_VERSION` | no common version | no |
| `E_STATE` | invalid protocol transition | no |
| `E_PEER_UID_MISMATCH` | wrong local user | no |
| `E_CAPABILITY_INVALID` | malformed or unknown capability | one handshake |
| `E_CAPABILITY_EXPIRED` | normal expiry | handshake |
| `E_CAPABILITY_REVOKED` | restart or explicit revoke | full replay |
| `E_FRAME_TOO_LARGE` | frame exceeds bound | no |
| `E_PAYLOAD_TOO_LARGE` | command payload exceeds bound | no |
| `E_JSON_DEPTH` | nesting exceeds bound | no |
| `E_STALE_CURSOR` | optimistic concurrency conflict | command-specific |
| `E_COMMAND_ID_CONFLICT` | mutated replay | no |
| `E_UNSUPPORTED_COMMAND` | handler absent | no |
| `E_SESSION_NOT_FOUND` | unknown session | no |
| `E_SESSION_CLOSED` | closed session | no |
| `E_SURFACE_UNAVAILABLE` | surface capability absent | no |
| `E_SURFACE_REVISION` | surface revision gap | snapshot |
| `E_FLOW_VIOLATION` | concurrency or slow-consumer violation | reconnect |
| `E_ALREADY_RUNNING` | live bridge exists | attach |
| `E_SOCKET_PATH_TOO_LONG` | UDS path exceeds platform bound | visible fallback |

Errors:

- are bounded and redacted
- never include tracebacks, tokens, raw request text, or file contents
- retain canonical refusal codes where applicable

## 17. Adversarial test requirements

- wrong-user UDS connection
- insecure directory or symlinked endpoint
- stale socket squatting
- unauthenticated loopback
- forged Host or Origin
- length prefix bomb
- partial-frame timeout
- invalid UTF-8
- excess JSON depth
- extra keys
- version mismatch
- expired and revoked capability
- capability surviving restart
- command duplicate and mutated duplicate
- concurrent cursor race
- unsupported handler
- surface revision gap
- output queue overflow
- slow consumer
- reconnect during stream
- restart during accepted command
- notification navigation without authorization
- personal browser profile attempt
- jail escape import
- raw Computer Use text or bytes in projection

## 18. Renewed-audit protocol amendments

This section is normative and supersedes conflicting earlier wording.

### Independent versions

- Native envelope version: `NATIVE_PROTOCOL_VERSION = 1`.
- Workspace command version: `birkin.workspace.contracts.PROTOCOL_VERSION`.
- `hello` always uses native envelope version 1 and carries supported native versions in its body.
- The server parses hello before selecting a version, returns both version sets on no overlap, and closes.
- Every post-ready frame must carry the selected native version.

### Raw-loopback authentication

The fallback is raw length-prefixed TCP, not HTTP or WebSocket. Host and Origin do not exist and are not security inputs.

- UDS initial hello is authenticated by same-user peer credentials and carries no bootstrap secret.
- Loopback initial hello carries the one-shot `bootstrap_secret`.
- Bootstrap records are private, expiring, atomically consumed, rotated after success, and reject concurrent reuse or stale replay.
- The bootstrap secret is rejected after ready.
- The `session_capability` returned by ready authenticates every later frame.

### Strict JSON and envelope state

The codec rejects duplicate object keys, `NaN`, positive/negative Infinity, excess depth, invalid UTF-8, trailing bytes, extra keys, and invalid identifiers. Encoding rejects non-finite numbers.

Per-kind validators define:

- exact body keys and types
- client/server direction
- legal connection states
- required response correlation
- connection-unique frame identifiers

### Integrity-safe events

Command fingerprints persisted for idempotency are SHA-256 digests of canonical command semantics. Public serializers omit the digest and redact bounded error text. Raw terminal input is never stored in journal event payloads or projected events.

### Browser commands

- `browser.navigate`: session, workspace, URL, lease epoch, sequence
- `browser.control.handoff`: session, workspace, current lease, target owner
- `browser.close`: session, workspace, lease epoch, sequence

### Computer Use commands

- `computer_use.consent`: grant, session, intent digest, prior receipt, decision
- `computer_use.execute`: grant, session, request digest, idempotency key

### Office and import commands

- `office.create`, `office.open`, `office.consent`
- `import.file` returns content hash, jailed URI, metadata, and receipt

### Terminal lease fields

`terminal.opened` returns `terminal_id`, `lease_id`, `lease_epoch`, `expires_at`, and output sequence. `terminal.input`, `terminal.resize`, `terminal.signal`, and `terminal.close` carry `lease_id` and `lease_epoch`. Cross-session, cross-connection, expired, revoked, and stale leases fail closed.

On disconnect the lease is revoked immediately. The PTY may remain read-only for a bounded grace period. Reconnect may fetch output state, then must explicitly reacquire a fresh lease before mutation.

### Codec error additions

| Code | Meaning | Disposition |
| --- | --- | --- |
| `E_ENVELOPE_KEYS` | envelope keys differ from schema | close |
| `E_PROTOCOL` | protocol name is unsupported | close |
| `E_KIND` | message kind is unsupported | close |
| `E_IDENTIFIER` | identifier is malformed | close |
| `E_FRAME_INCOMPLETE` | frame ended early | close |
| `E_FRAME_TRAILING_DATA` | frame contains trailing bytes | close |
| `E_INVALID_UTF8` | body is not UTF-8 | close |
| `E_JSON` | body is not strict JSON | close |
| `E_DUPLICATE_KEY` | JSON object repeats a key | close |
| `E_NONFINITE_NUMBER` | JSON contains NaN or Infinity | close |
| `E_DIRECTION` | kind came from the wrong endpoint | close |
| `E_CORRELATION` | response correlation is missing or invalid | close |
| `E_DUPLICATE_FRAME_ID` | frame id was reused on one connection | close |
| `E_TERMINAL_LEASE` | terminal lease is absent, stale, or mismatched | no silent retry |
