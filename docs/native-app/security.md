# Native Application Security Boundary

Status: shipped trust boundary for the local macOS client.

## Authority

Python alone decides whether an operation is allowed, whether approval or
consent is required, how it executes, and which audit and recovery records are
canonical. SwiftUI renders projected state and submits typed intent. A toggle,
focused window, menu command, notification tap, voice transcript, or local
process observation is never authorization.

## Local endpoint authentication

### Unix domain socket

The bridge creates its runtime directory as `0700` and socket as `0600`. Before
binding, it refuses a socket path or parent that is a symbolic link. On accept it
reads platform peer credentials (`getpeereid`, `SO_PEERCRED`, or
`LOCAL_PEERCRED`) and rejects an unavailable, malformed, or different UID. This
prevents filesystem access alone from being treated as client identity.

### Private loopback

The fallback is explicit and binds only `127.0.0.1`. Its private endpoint record
is `0600` and contains a random, two-minute, one-shot bootstrap secret. The
first `hello` exchanges that secret and rotates the record immediately. The raw
socket protocol is not HTTP and does not claim Host or Origin enforcement.

Both transports receive a random session capability scoped to bridge instance,
connection, surface, and view. Capabilities exist only in Python and Swift
memory, use a 15-minute sliding expiry with an eight-hour hard ceiling, rotate
in band, and are revoked on disconnect, expiry, or bridge teardown. Bootstrap
secrets and session capabilities cannot approve product actions.

## Strict and bounded input

The boundary refuses oversized or incomplete frames, payloads over 65,536,
invalid UTF-8 or strict JSON, duplicate keys, non-finite numbers, excessive
nesting, unexpected keys, invalid direction/state/correlation, stale cursors,
changed command replays, excess concurrency, and slow-consumer desynchronization.
Public errors are typed and bounded.

## Redacted projection and diagnostics

Redaction happens in Python before records cross the process boundary. Recursive
projection replaces keys such as tokens, credentials, cookies, authorization,
passwords, bootstrap secrets, and session capabilities. It removes replay
fingerprints, strips traceback/file lines, recognizes common bearer and provider
token forms, caps public text, and replaces terminal input with terminal ID,
sequence, and `redacted: true`.

Swift capabilities are memory-only. Native diagnostics are bounded and do not
persist raw frames. Desktop notifications use fixed copy and opaque item IDs;
untrusted canonical content does not enter notification title, body, or deep
link. Approval notifications contain no decision actions. Their route opens the
in-app canonical approval view, so a notification remains navigation rather
than authority.

## File, product, and process boundaries

- **Jailed imports:** drag-and-drop intent carries only a source path to Python.
  Python opens with `O_NOFOLLOW` where available, requires a regular file,
  copies bytes into a private jail under a generated name, and returns only a
  reference and SHA-256/byte-count receipt. Caller-selected destinations and
  source paths do not cross the canonical result boundary.
- **Browser Aside:** Python exposes a private per-session Browser authority and
  revisioned redacted projection; the shell does not attach personal profiles
  or invent a control lease.
- **Computer Use:** status is distinct from consent. Foreground mutation remains
  behind Python's exact identity, policy, and one-shot authority.
- **Office:** create/open commands retain Python path identity, jail, provenance,
  and active-content checks. Swift receives projected document references and
  receipts, not unrestricted file authority.
- **Owned Terminal:** Python owns the PTY and process tree. Approval precedes the
  lease; every input/resize/signal/close mutation requires current authority,
  and only allowlisted signals are accepted. Secret input is not projected.
  Each macOS terminal runs in a launchd resource coalition under a Seatbelt
  profile that denies Mach, network, shared-memory IPC, and terminal-originated
  process signalling. App exit quiesces and rescans the
  coalition before killing every member, including double-forked `setsid()`
  descendants. Non-Darwin bridges do not advertise this command set.
- **Bridge supervision:** Swift terminates or restarts only children it spawned.
  An externally discovered bridge is attached without ownership and is left
  running at app shutdown. Restart loops are bounded.

## Approval races

An approval decision is resolved once by the Python approval authority. If
another UI or worker wins the race, the native response is normalized to
`answered_elsewhere`; Swift cannot overwrite the decision or infer success from
its own button state. A failed authority decision is separately reported as
`rejected_by_authority` with bounded text.

## Persistence and packaging

The native client may persist presentation preferences only. It does not persist
provider credentials, protocol capabilities, sessions, Working Memory,
approvals, receipts, Browser data, Computer Use artifacts, Office contents,
terminal input, or pending command payloads.

The repository package is signed but intentionally not App Sandbox-enabled:
PTYs, private local sockets, Accessibility, and Screen Recording need facilities
outside the initial sandbox profile. This is not a weakening of Python policy
or macOS privacy controls. Local authentication, typed command gates, explicit
approval/consent, jailed imports, redaction, and OS permissions remain the
security boundary.

Packaging refuses dirty source. The app-signature-sealed manifest records the
clean revision and exact product version with architecture-specific helper and
browser hashes. Swift requires that manifest version to equal its generated
version and refuses a missing, wrong-architecture, symlinked, or changed helper.
Every embedded or external bridge must independently return the same exact
`ready.server_version`. Frozen Python removes any inherited Playwright path,
accepts only its bundled browser tree for the selected architecture, and
refuses missing, malformed, wrong-architecture, symlinked, wrong-size, or
changed browser bytes with bounded remediation text.

`BIRKIN_NATIVE_JOURNEY=1` is an explicit, disabled-by-default release-QA seam.
It can drive real provider and product actions, so only the release harness
should set it. It invokes the same packaged-app controls and bridge as the UI;
it grants no protocol capability, approval, consent, terminal lease, Browser,
Computer Use, Office, or import authority. The acceptance verifier requires
separate real-provider probe and chat-success markers and rejects known
provider-error or fixture text before accepting journey evidence.

Browser executable code and helper code are signed before the enclosing app.
With a Developer ID identity, the packaging script uses hardened runtime and a
timestamp. Without one, it signs ad hoc with no hardened-runtime option or
entitlements. The script does not notarize the artifact. Notarization,
stapling, and Gatekeeper assessment are separate credentialed public-release
gates; the credential-free build is not a notarized public download.
