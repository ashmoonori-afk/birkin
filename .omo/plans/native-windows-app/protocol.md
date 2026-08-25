# Birkin Native Windows Protocol Contract

Status: implemented Phase 3 development-preview contract
Wire protocol: `birkin-local-1`
Native envelope version: `1`
Transport on Windows: authenticated raw loopback

## 1. Placement decision

Windows reimplements the frame, strict JSON, envelope, connection-state,
handshake, and cursor-reduction layers in C#, just as macOS implements them in
Swift. It does not call Python through an embedded interpreter, generate a C
ABI, share a socket library, or use a sidecar to translate messages.

The implementation lives in `Birkin.Native.Protocol`. This choice keeps the
Windows process a normal command-line-buildable .NET application and avoids
moving authority or runtime behavior out of Python. Cross-language reuse is at
the contract-fixture level, not the executable-code level.

The Python implementation remains normative. Swift and C# are independent
consumers that must pass the same Python-generated vectors and live-bridge
journeys. A C# model that is convenient but cannot round-trip those vectors is
wrong.

## 2. Framing and strict JSON

Every frame remains exactly:

```text
4-byte big-endian unsigned body length
N bytes of UTF-8 JSON
```

`N` may not exceed 262,144. The streaming reader checks the length before
allocating the body, reads exactly that body, and then begins the next frame.
The complete-frame decoder rejects a short header, short body, oversized body,
and trailing bytes with the existing typed codes.

The C# decoder uses `Utf8JsonReader` behind an ordered `NativeJsonValue` tree;
it does not deserialize untrusted frames directly into permissive POCOs.
Object members are retained in wire order for byte-identical re-encoding and a
per-object key set rejects duplicates before values are admitted. The parser
also rejects:

- malformed UTF-8 and malformed JSON;
- lone UTF-16 surrogates;
- non-finite numbers;
- integers outside signed 64-bit range;
- generic parser nesting beyond 128;
- envelope-body nesting beyond 12;
- non-object envelopes or bodies.

The envelope has exactly `protocol`, `protocol_version`, `kind`, `id`,
`in_reply_to`, and `body`, in that serialized order. Kind-specific validators
require the exact existing body key sets. Identifiers match
`[A-Za-z0-9._:-]{1,128}`. Each connection tracks the newest 1,024 inbound and
outbound frame identifiers in insertion order and reports
`E_DUPLICATE_FRAME_ID` for reuse still in that window.

Serialization uses UTF-8 without a BOM, no insignificant whitespace, lower-case
JSON literals, the existing Python-compatible float spelling, and no escaping
of valid Korean text merely to make it ASCII. The length prefix counts encoded
UTF-8 bytes, not C# characters.

## 3. Announcement and discovery attach seam

`BridgeProcess` writes one JSON line to stdout when the listener is ready. The
Windows client and the QA harness attach through that line; they do not scan
ports or guess a runtime directory. The accepted announcement has the existing
fields:

```json
{
  "event": "listening",
  "transport": "loopback",
  "pid": 33132,
  "session_id": "native-app",
  "instance_id": "d798defb159c4346a35ed702ab479c4b",
  "server_version": "0.4.273",
  "discovery_path": "C:\\...\\native\\endpoint.json"
}
```

The PID is diagnostic only for an external attachment. It never grants process
ownership. The client opens and strictly parses the announced owner-only
Python discovery record described in `architecture.md`. It requires
`transport == "loopback"`,
`host == "127.0.0.1"`, a live expiry, protocol version 1, and agreement between
the announcement and record for instance and server version.

The bootstrap secret is read once and sent once. It is not logged, included in
diagnostics, copied to a view model, or retained after `ready`. The app never
falls back from a refused record to an unauthenticated port.

The development external attach command is
`Birkin.Native.App.exe --bridge-announcement-file <path>`, where the file
contains exactly the captured `listening` line. Normal development-preview
startup spawns an exact owned `Process`, reads the same announcement parser from
redirected stdout, and retains that process object as the only stop token;
there is no second attach protocol. Attach never kills. Handle-based discovery
final-path, reparse, owner, and protected-DACL verification remains deferred LOW
hardening; current authentication is the Python owner-only record plus one-shot
secret.

## 4. Negotiation and handshake

The state machine is strict:

1. Connect to the recorded loopback port.
2. Send `hello` as a version-1 envelope with:
   - `client = "birkin-native-windows"`;
   - the independently built client product version and build identity;
   - `supported_protocol_versions = [1]`;
   - `surface = "windows"`;
   - `view_id = "window-main"`;
   - the discovery record's `bootstrap_secret`.
3. Require a correlated `ready` whose `in_reply_to` is the hello frame ID.
4. Require selected protocol version 1 and require `server_version` to equal
   the client package version exactly. The discovery and ready versions must
   also agree.
5. Retain the ready capability only inside the connection context.
6. Subscribe to the exact `ready.session_id`; the client never invents or
   substitutes a session.

There is no silent downgrade. An envelope version other than 1 is rejected even
if its body advertises version 1. An incompatible ready enters the visible
`VERSION MISMATCH` state and does not subscribe.

The initial subscription body is exact:

```json
{
  "session_id": "<ready.session_id>",
  "after_cursor": 0,
  "known_instance_id": null,
  "session_capability": "<in-memory token>",
  "surfaces": {}
}
```

The exact client identity is `surface = "windows"` and
`view_id = "window-main"`; no alternate Windows view may acquire a second
capability scope. A canonical `snapshot` is required before the shell shows
`LOCAL · PRIVATE`. Surfaces and commands remain data advertised by Python,
never client feature flags.

The client validates all ready limits. It refuses a server-advertised frame or
payload limit larger than its compiled safety ceiling and obeys a smaller
server limit. The normal command lane is one in-flight command; steer,
interrupt, and resume use only the separately bounded control lanes defined by
the existing protocol.

## 5. Projection, cursor, and surface rules

A full snapshot replaces the workspace projection atomically after all of its
fields, session ID, protocol version, instance ID, and reset reason validate.
A partially decoded snapshot is never rendered.

For an event with cursor `C`, the only accepted live transition is:

```text
C == current_cursor + 1
```

An event at or behind the current cursor is a protocol refusal, not an
idempotent UI update. An event ahead by more than one is a gap. On a gap the
shared store keeps the previous projection only as visibly stale presentation,
revokes mutation authority, and `BridgeSession` performs one gated canonical
replay request with:

```text
after_cursor = last accepted cursor (or the server's desync resume hint)
known_instance_id = negotiated instance
all known surface revisions = 0
```

`stream.desynchronized`, surface gaps, and heartbeat misses enter the same
repair episode. Additional repair signals cannot send another subscription
while replay is in flight. A replacement canonical snapshot alone returns the
store to `Live` and restores mutation authority. This deliberately prefers one
complete authoritative snapshot over a clever client-side repair.

An ordinary socket reconnect without a detected gap may offer the last
contiguous cursor, known instance, and known surface revisions. The server may
then send contiguous `event` frames, a reset `snapshot`, and any required
`surface_snapshot` frames. The client accepts either ordering allowed by the
existing subscription implementation and does not require a made-up
"replay complete" message.

A `surface_event` advances only from revision `R` to `R + 1`. A missing surface
or revision gap enters the same canonical repair episode and requests zero
revision state rather than being repaired locally. Targeted
surface-only optimization remains deferred until measurements show a need.

## 6. Instance reset

`ready.instance_id` names one bridge lifetime. It scopes capabilities,
projection replay hints, and terminal leases.

If a newly negotiated instance differs from the last known instance, the
client immediately discards:

- the current and predecessor capabilities;
- the workspace projection and cursor;
- all product-surface projections and revisions;
- pending receipt correlations and in-flight command UI state;
- terminal leases and writable terminal presentation.

It then subscribes with cursor 0, null known instance, and zero surface
revisions. A snapshot with `reset_reason = "instance_changed"`, `"initial"`,
`"cursor_ahead"`, or `"cursor_gap"` is accepted only when its body instance
matches the negotiated ready instance. The reset reason is diagnostic state;
it never authorizes retrying a mutation.

## 7. Sole reader, commands, receipts, and errors

Production composes one `BridgeSession` over one shared
`NativeProjectionStore`. `BridgeSession` owns the lifetime receive pump and
routes every snapshot, event, surface update, receipt, heartbeat, renewal,
desynchronization, and disconnect. Its `ReceiveAsync` rejects callers, so the
shell cannot race a second reader. One pending command waiter is correlated by
command ID; disconnect or recovery faults it and revokes mutation authority.

Every command uses a stable command ID, workspace protocol version, expected
cursor, exact type and payload, plus client context with `surface = "windows"`
and the current view ID. The outer command frame carries the current connection
capability.

Only Python-advertised command types can be submitted. A receipt advances UI
state only after its correlation and body validate. `E_STALE_CURSOR` refreshes
the projection and preserves the user's draft, but does not automatically
resubmit consequential work. Approval, configuration, import, Office,
Computer Use, Browser, and terminal mutations are never silently replayed.
`chat.interrupt` may use the existing narrowly documented retry behavior; no
other command inherits it.

Typed errors retain their existing codes and bounded public text. The client
shows the public message and code, never a raw payload, stack trace, secret,
capability, or exception object. Unknown error codes remain bounded protocol
errors and do not become success.

On `capability.renewed`, the token and both expiries must validate before the
connection context atomically replaces the current token. New frames use only
the replacement. `ping` receives a correlated `pong` carrying the current
capability. Idle receive timeouts shorter than the server heartbeat are not
interpreted as disconnects.

## 8. Cross-language conformance

C# consumes the same checked-in Python-generated fixtures as Swift. It does not
maintain a hand-copied Windows fixture:

- `macos/BirkinNativeApp/Tests/BirkinNativeProtocolTests/GoldenVectors/native-protocol-vectors.json`
  is linked as test content by `Birkin.Native.Protocol.Tests.csproj`;
- `macos/BirkinNativeApp/Tests/BirkinNativeProtocolTests/GoldenVectors/native-projection-vectors.json`
  is linked the same way for reducer tests.

`scripts/native/generate_golden_vectors.py` remains the producer for protocol
vectors. CI regenerates the artifact with the real Python codec and requires a
clean diff. Every C# vector test must:

1. base64-decode the frame;
2. decode it to the expected ordered envelope and kind;
3. compare the semantic body to the fixture;
4. re-encode byte-for-byte identically;
5. verify the frame byte count and protocol limits in the fixture.

Projection tests apply the Python-generated snapshot, each of the 14 contiguous
events, and the gap event, comparing machine-consumed state after every step.
Swift runs its existing tests against those same files.

In the resilience phase, the generator is extended with a machine-consumed
negative corpus of raw frames and expected Python error codes for duplicate
keys, invalid UTF-8, non-finite values, depth, signed-64 overflow, duplicate
frame IDs, direction, state, correlation, and bounds. Both Swift and C# must
produce the same stable code. This fixture tests values, not exception prose.

The conformance gate is therefore three-way:

```text
Python generates and self-round-trips
        + Swift decodes/re-encodes/reduces
        + C# decodes/re-encodes/reduces
        + C# live-loopback journey talks to the real Python bridge
```

A protocol change is incomplete until the Python generator, both client suites,
the normative protocol documentation, and the protocol-version decision agree.
Golden files are evidence, not a mechanism for silently extending version 1.
