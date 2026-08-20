# Native Application Architecture

Status: shipped repository contract for the macOS client.

## Authority boundary

Birkin's macOS application is a thin SwiftUI shell. It connects to the local
bridge, renders Python-produced snapshots and events, and submits explicit
versioned commands. It is not a second agent runtime.

Python remains authoritative for session and Working Memory state, policy,
execution, approvals and consent, terminal process trees, audit records, and
recovery. Swift owns presentation state and local desktop integration only. A
control being visible, enabled, focused, or activated never grants authority.

## Components

### Python bridge

`birkin/native/` adapts the existing workspace authorities to the local native
protocol. The bridge:

- serves a private Unix domain socket (UDS), or authenticated `127.0.0.1`
  loopback when explicitly selected;
- negotiates protocol version, limits, commands, surfaces, and optional voice
  availability;
- authenticates UDS clients by peer UID and loopback clients by a rotating
  one-shot bootstrap secret, then requires a connection-scoped capability;
- routes commands to Python workspace, session, configuration, terminal,
  Browser Aside, Computer Use, Office, and jailed-import authorities;
- emits canonical snapshots, cursor-contiguous events, receipts, and redacted
  revisioned product-surface projections.

The dependency direction is one way: existing runtime and workspace modules do
not import the native bridge. The bridge is an adapter over those authorities.

### Swift protocol and shell

`macos/BirkinNativeApp/` contains:

- strict frame, JSON, envelope, handshake, UDS, and loopback implementations;
- an ephemeral projection store with cursor-gap and instance-reset handling;
- SwiftUI sessions, conversation, Working Memory, owned Terminal, approvals,
  Activity, Browser Aside, Computer Use, and Office presentations;
- menu navigation, redacted notifications and deep links, jailed file-import
  intent, optional voice gating, accessibility, and recovery presentation.

Capabilities and authoritative workspace data stay in memory. Swift may retain
presentation preferences, but it does not create a second session database or
persist capabilities, approvals, receipts, terminal input, or product data.

## Projection and command flow

1. Swift connects locally and sends `hello`.
2. Python authenticates it and returns `ready` with limits and capabilities.
3. Swift subscribes with its last cursor, known bridge instance, and known
   surface revisions.
4. Python returns a full snapshot when the client is new, ahead, or attached to
   a changed instance; otherwise it replays contiguous events. Surface gaps are
   repaired with full per-surface snapshots.
5. Swift submits a strict workspace command with a stable command ID and
   expected cursor. Python validates, executes, records, and returns the public
   receipt or typed error.

The projection store is a cache, not authority. Reconnect clears stale
capabilities and terminal leases before state is trusted again. Interrupted
mutations are not inferred from UI state; canonical replay or an explicit retry
determines their outcome.

## Supervisor ownership

The Swift supervisor distinguishes an app-spawned bridge from an externally
managed bridge. It may terminate or restart only a process returned by its own
spawn closure. Discovery of an existing endpoint attaches without taking
ownership, and shutdown leaves that external process untouched. App-owned
crashes are restarted with a ceiling of five exits in sixty seconds; reaching
the ceiling produces a bounded stopped state instead of a crash loop.

The packaged executable also supports attachment to a supplied live UDS
endpoint through `BIRKIN_NATIVE_SOCKET`, which is the exercised package path.

## Packaging decision

`scripts/native/package_macos_app.sh` builds a universal (`arm64` and `x86_64`)
SwiftPM release binary, assembles `Birkin.app` with bundle identifier
`com.birkin.native`, and signs inside-out. It uses a Developer ID identity and
hardened runtime when credentials are available; otherwise it produces an
ad-hoc-signed development artifact. Notarization is therefore deferred when
credentials are absent.

App Sandbox is intentionally disabled in this package. The shipped architecture
uses PTYs, private local sockets, Accessibility, and Screen Recording facilities
outside the initial sandbox profile. Those operations remain constrained by
Python policy, typed capability and consent gates, peer authentication, and OS
privacy permissions rather than being misrepresented as sandbox-compatible.
