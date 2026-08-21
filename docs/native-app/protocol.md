# Birkin Local Native Protocol

Protocol: `birkin-local-1`, envelope version `1`

Status: shipped by the Python bridge and Swift protocol package.

## Transport and framing

The preferred macOS transport is a private UDS. Its path and parents may not
traverse symlinks, its runtime directory is mode `0700`, the socket is mode
`0600`, and the accepted peer UID must equal the bridge user's effective UID.
The explicitly selected fallback binds only `127.0.0.1` and publishes a private
mode-`0600` endpoint record containing a one-shot bootstrap secret. This is a
raw framed socket protocol, not HTTP; it has no Host or Origin fields.

Every frame is exactly:

```text
4-byte big-endian unsigned JSON byte length
that many bytes of UTF-8 JSON
```

The maximum JSON body is 262,144 bytes. Incomplete frames, trailing bytes,
invalid UTF-8, duplicate object keys, non-finite numbers, unexpected envelope
keys, and excessive nesting are refused. An envelope has exactly
`protocol`, `protocol_version`, `kind`, `id`, `in_reply_to`, and object-valued
`body`. Identifiers match `[A-Za-z0-9._:-]{1,128}`.

A nested workspace command carries its own protocol version, stable command ID,
expected cursor, type, payload, and client context. Its payload has a canonical
65,536 bound and the advertised maximum JSON body depth is 12. `ready` also
advertises maximum frame bytes, eight in-flight commands, and 32 subscriptions.

Frame identifiers must be unique inside a bounded replay window: each endpoint
remembers the most recent 1,024 identifiers it sent or received on that
connection. Reusing an identifier still inside that window is refused as
`E_DUPLICATE_FRAME_ID`. Older identifiers are evicted, so a long-lived
streaming connection processes an unbounded number of frames with bounded
memory and is never torn down for age alone.

## Message kinds

These are all registered envelope kinds in `birkin/native/protocol.py`:

| Kind | Direction and purpose |
| --- | --- |
| `hello` | client -> server: negotiate and authenticate |
| `ready` | server -> client: selected version, identity, limits, capability, commands, and surfaces |
| `subscribe` | client -> server: session cursor, known instance, and surface revisions |
| `snapshot` | server -> client: full canonical workspace projection |
| `event` | server -> client: one cursor-bearing workspace event |
| `surface_snapshot` | server -> client: full revisioned product-surface projection |
| `surface_event` | server -> client: one revisioned product-surface event |
| `command` | client -> server: strict nested workspace command |
| `receipt` | server -> client: public canonical command result |
| `error` | server -> client: bounded typed refusal |
| `capability.renewed` | server -> client: replacement in-memory capability |
| `stream.desynchronized` | server -> client: outbound stream lost continuity |
| `ping`, `pong` | either permitted direction: liveness and correlation |
| `goodbye` | client -> server: orderly authenticated close |

The Python workspace command schema recognizes chat send/steer/interrupt/resume/
retry; session create/select/rename/compact; task send/cancel; approval and
question answers; cron create/pause/resume/remove; memory write/link; terminal
create/input/resize/signal/close/snapshot; Browser start/navigate; Office
create/open; jailed file import; skill reload; checkpoint restore; config set;
and gateway restart. `ready.capabilities.commands` is the authoritative subset
actually registered for a connection. Unsupported registered-schema commands
are not simulated by Swift and return `E_UNSUPPORTED_COMMAND`.

## Handshake and capability lifecycle

`hello` identifies the client version/build, supported protocol versions,
`macos` surface, and view. A loopback hello must present the endpoint record's
one-shot `bootstrap_secret`; successful exchange rotates the disk secret. UDS
hello instead relies on the accepted same-user peer credential. There is no
silent protocol downgrade.

`ready` returns the bridge `instance_id`, the `session_id` the bridge serves,
the transport, negotiated limits and features, and a random session capability
scoped to that instance, connection, surface, and view. The body carries
exactly `protocol_version`, `server_version`, `instance_id`, `session_id`,
`transport`, `capability`, `limits`, and `capabilities`; `session_id` is
required, and the client subscribes to that session rather than guessing one. Every post-ready client frame carries that capability. Swift
keeps it in memory only. The default sliding lifetime is 15 minutes with an
eight-hour hard connection ceiling. Near expiry the server sends
`capability.renewed`; replacement revokes the previous token. Tokens are also
revoked at disconnect, `goodbye`, expiry, or bridge teardown. A capability does
not replace Python approval, terminal lease, Browser control, Computer Use, or
Office consent authority.

## Cursor, replay, and surface revisions

A subscription sends `after_cursor`, `known_instance_id`, and known surface
revisions. With no known instance, a changed instance, or a cursor ahead of
Python, the server returns a full snapshot with reset reason `initial`,
`instance_changed`, or `cursor_ahead`. For the same instance it replays events
only when every cursor is contiguous. A gap produces a full snapshot with
`cursor_gap`. Full reconnect snapshots clear terminal leases and mark terminals
read-only until Python grants new authority.

Swift applies only contiguous events. A projection gap requests canonical
recovery rather than guessing. Product surfaces have independent revisions;
Python returns full `surface_snapshot` records where a client's revision cannot
be advanced safely. `stream.desynchronized` likewise requires replay from
canonical state.

Product surfaces also update live. After a canonical `browser.updated`,
`office.updated`, or `computer.updated` workspace event, the bridge queues a
`surface_event` for that surface behind the event itself, so ordering, cursor
semantics, and redaction are preserved and the client renders the new state
without resubscribing. Its `revision` is the surface's next monotonic
revision; a client that cannot advance contiguously asks for a full surface
snapshot instead of guessing.

Command IDs make duplicate delivery idempotent. Reusing an ID with changed
semantics returns `E_COMMAND_ID_CONFLICT`; an obsolete expected cursor returns
`E_STALE_CURSOR` and its current cursor. The shell does not silently replay
approval, configuration, terminal, Browser, Computer Use, or Office mutations.

## Typed errors

The shipped Python native boundary emits these codes:

| Code | Meaning |
| --- | --- |
| `E_ENVELOPE_KEYS` | envelope key set is not exact |
| `E_PROTOCOL`, `E_PROTOCOL_VERSION` | protocol name or version is unsupported |
| `E_KIND`, `E_IDENTIFIER`, `E_BODY` | kind, identifier, or typed body is invalid |
| `E_JSON`, `E_JSON_DEPTH`, `E_DUPLICATE_KEY`, `E_NONFINITE_NUMBER` | strict JSON violation |
| `E_INVALID_UTF8` | frame body is not UTF-8 |
| `E_FRAME_TOO_LARGE`, `E_FRAME_INCOMPLETE`, `E_FRAME_TRAILING_DATA` | frame bound or completeness violation |
| `E_DIRECTION`, `E_STATE`, `E_CORRELATION` | sender direction, state transition, or reply correlation is invalid |
| `E_DUPLICATE_FRAME_ID`, `E_FLOW_VIOLATION` | connection ID reuse or bounded-flow violation |
| `E_SOCKET_PATH`, `E_SOCKET_PATH_TOO_LONG`, `E_ALREADY_RUNNING`, `E_TRANSPORT` | local endpoint or transport refusal |
| `E_PEER_UID_MISMATCH` | UDS peer is unavailable, invalid, or not the bridge user |
| `E_BOOTSTRAP_INVALID`, `E_BOOTSTRAP_EXPIRED` | loopback one-shot secret is invalid or expired |
| `E_CAPABILITY_INVALID`, `E_CAPABILITY_EXPIRED` | post-ready capability is wrong for the scope or no longer live |
| `E_SESSION_NOT_FOUND` | requested workspace session is not served |
| `E_STALE_CURSOR`, `E_COMMAND_ID_CONFLICT`, `E_UNSUPPORTED_COMMAND` | workspace concurrency, replay, or handler refusal |
| `E_CONFIG_REJECTED` | canonical configuration validation rejected the mutation |
| `E_WORKING_MEMORY_REVISION`, `E_WORKING_MEMORY_BUDGET` | Working Memory compare-and-swap or render-budget refusal |
| `E_TERMINAL_APPROVAL_REQUIRED` | shell approval must resolve before a terminal lease is issued |
| `E_TERMINAL_LEASE_REQUIRED` | terminal mutation lacks the current lease |
| `E_TERMINAL_SEQUENCE` | terminal input is duplicated or out of order |
| `E_TERMINAL_SIGNAL` | signal is outside the process-tree allowlist |

Errors expose bounded public text, not tracebacks or raw secret-bearing payloads.
The protocol and projection fixtures contain 21 Python-generated frame vectors,
a canonical snapshot, 14 events, and a gap event, all decoded by Swift tests.

## Cross-language JSON narrowings

The Python and Swift codecs both narrow generic JSON in two places:

- A lone UTF-16 surrogate (`\uD800`-`\uDFFF` not forming a valid pair) is
  refused as `E_JSON`, because Swift `String` cannot represent it.
- An integer outside the signed `Int64` range is refused as `E_JSON`.

Before envelope validation, the Swift parser also has a depth-128 recursion
guard to bound parser stack use. Exceeding it is refused as `E_JSON_DEPTH`. This
does not relax the wire contract: after parsing, the envelope `body` still has
the shared maximum depth of 12.
