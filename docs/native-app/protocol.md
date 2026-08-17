# Birkin Local Native Protocol

Protocol: `birkin-local-1`

Status: planned. Version 1 is not yet served by any released build.

## Transport

Primary:

- Unix domain socket
- private runtime directory
- same-user peer credentials
- short-lived capability

Fallback, used only after a declared Unix socket failure or explicit diagnostic configuration:

- `127.0.0.1` only
- pinned Host and Origin
- private `0600` endpoint record with a dedicated one-shot bootstrap secret
- the client reads the secret only at connect time
- successful hello consumes and rotates it, then returns the normal short-lived in-memory capability

No public bind or unauthenticated fallback is supported.

The application visibly reports that fallback is active and why.

## Framing

Each frame is:

```text
4-byte big-endian unsigned body length
UTF-8 JSON body
```

The frame size, command payload, JSON depth, subscriptions, in-flight commands, event queue, and diagnostics are bounded.

## Negotiation

The client sends `hello` with:

- application and build version
- supported protocol versions
- `macos` surface identity
- view identifier
- fallback capability when required

The server returns `ready` with:

- selected protocol version
- server and instance identity
- renewed capability
- limits
- registered command capabilities
- negotiated surface capabilities

When the client and server share no protocol version, the server returns a terminal version-mismatch error listing both version sets and closes the connection. The protocol never silently downgrades.

## Workspace messages

The protocol carries:

- `subscribe`
- canonical workspace `snapshot`
- canonical workspace `event`
- strict workspace `command`
- public command `receipt`
- bounded `error`
- `ping`, `pong`, and `goodbye`

Workspace commands retain the Python protocol version, command identifier, expected cursor, strict payload, and client context.

## Errors

| Code | Meaning | Retry disposition |
| --- | --- | --- |
| `E_PROTOCOL_VERSION` | no common protocol version | terminal |
| `E_STATE` | invalid protocol transition | terminal |
| `E_PEER_UID_MISMATCH` | wrong local user | terminal |
| `E_CAPABILITY_INVALID` | malformed or unknown capability | one full handshake |
| `E_CAPABILITY_EXPIRED` | normal capability expiry | full handshake |
| `E_CAPABILITY_REVOKED` | restart or explicit revocation | full replay |
| `E_FRAME_TOO_LARGE` | frame exceeds the advertised bound | terminal |
| `E_PAYLOAD_TOO_LARGE` | command payload exceeds the canonical bound | terminal |
| `E_JSON_DEPTH` | JSON nesting exceeds the canonical bound | terminal |
| `E_STALE_CURSOR` | optimistic concurrency conflict | command-specific |
| `E_COMMAND_ID_CONFLICT` | one identifier was reused with a changed payload | terminal |
| `E_UNSUPPORTED_COMMAND` | no registered Python handler exists | terminal |
| `E_SESSION_NOT_FOUND` | session identity is unknown | return to Sessions |
| `E_SESSION_CLOSED` | session is closed | create or select another session |
| `E_SURFACE_UNAVAILABLE` | negotiated surface capability is absent | terminal for that surface |
| `E_SURFACE_REVISION` | surface event revision has a gap | request a full surface snapshot |
| `E_FLOW_VIOLATION` | concurrency or slow-consumer bound was exceeded | reconnect |
| `E_ALREADY_RUNNING` | a live bridge already owns the endpoint | attach to the live bridge |
| `E_SOCKET_PATH_TOO_LONG` | the Unix socket path exceeds the platform bound | visibly use the allowed fallback |

Errors are bounded and redacted. They never include tracebacks, tokens, raw request text, or file contents, and they retain canonical refusal codes where applicable.

## Surface projections

Browser Aside, Computer Use, Office, Working Memory, and Terminal use separately negotiated, revisioned surface snapshots and events constructed by Python.

Projection payloads exclude provider tokens, raw binary artifacts, personal browser data, secret input, and hidden execution state.

## Reconnect

- cursor gaps require full workspace replay
- surface revision gaps require a full surface snapshot
- a changed Python instance invalidates capabilities and all native authority projections
- duplicate command recovery uses the original command identifier
- a changed payload with the same identifier is rejected

Only `chat.interrupt` may automatically retry once after a stale cursor. Every other command refreshes state, preserves the draft, shows an inline conflict, and requires explicit re-submission. Approval, config, checkpoint, terminal signal, Browser control, Computer Use, and Office consent actions are never silently replayed.

## Capabilities

The local capability is random, scoped to a bridge instance and connection, and kept in Swift memory only. It carries a sliding time-to-live plus a hard per-connection ceiling, both advertised in `ready`. The server sends `capability.renewed` before expiry; the client swaps the token in memory without a connection-state change. A failed renewal triggers one full handshake. The capability is revoked on close, goodbye, expiry, explicit revoke, or bridge restart.

The one-shot loopback bootstrap secret is a separate, narrowly scoped disk bootstrap mechanism. It is not a provider credential or a session capability.

It does not replace approval decisions, Computer Use consent, Browser control leases, Office active-content consent, or policy changes.

## Strict codec additions

The native envelope has an independent version from nested workspace commands. Initial `hello` uses native envelope version 1 so supported-version negotiation remains parseable.

The raw private-loopback transport uses `bootstrap_secret` only for hello. It does not use HTTP Host or Origin. UDS hello is authenticated by same-user peer credentials. `session_capability` authenticates post-ready frames.

The codec also publishes:

| Code | Meaning |
| --- | --- |
| `E_ENVELOPE_KEYS` | invalid envelope key set |
| `E_PROTOCOL` | unsupported protocol name |
| `E_KIND` | unsupported message kind |
| `E_IDENTIFIER` | malformed identifier |
| `E_FRAME_INCOMPLETE` | incomplete frame |
| `E_FRAME_TRAILING_DATA` | trailing frame bytes |
| `E_INVALID_UTF8` | invalid UTF-8 |
| `E_JSON` | invalid strict JSON |
| `E_DUPLICATE_KEY` | duplicate JSON key |
| `E_NONFINITE_NUMBER` | NaN or Infinity |
| `E_DIRECTION` | wrong sender direction |
| `E_CORRELATION` | invalid response correlation |
| `E_DUPLICATE_FRAME_ID` | reused connection frame identifier |
| `E_TERMINAL_LEASE` | invalid terminal lease |
