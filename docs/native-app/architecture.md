# Native Application Architecture

Status: shipped repository contract for the macOS client.

## Windows Phase 3 companion architecture

The Windows client is a .NET 8 WPF thin shell over authenticated raw loopback.
Production composition creates one `NativeProjectionStore`, one sole-reader
`BridgeSession`, and one shell coordinator over that same store. The session
routes every frame and owns canonical recovery: gap, desynchronization,
heartbeat loss, or disconnect revokes mutation authority; one replay episode
remains in flight until a replacement snapshot restores `Live` state. There is
no manual receive path or second authority. See
`windows/BirkinNativeApp/src/Birkin.Native.Protocol/Transport/BridgeSession.cs`
and its `BridgeSessionTests.cs`.

External attach never grants process ownership and is never killed. An owned
bridge is the exact process object returned by the spawn closure; its fifth exit
in a rolling 60 seconds stops restart, and session disposal precedes process
stop. Terminal and Browser regions remain visible truth-telling placeholders by
direct user request and cannot invent authority.

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

### Windows progress and attention

Python emits bounded progress items into canonical Activity and retains the
newest 100 items.
The Windows reducer handles progress, tool lifecycle, and fixed-copy
notification events without creating local authority. A presentation-only
tracker recognizes each newly pending opaque approval ID once. The WPF host
shows the pending count, defers a pre-load flash until the window loads, and
explicitly stops flashing when no approval remains; selecting that taskbar
entry opens the existing canonical approval surface.

### Browser control scope

Python registers `browser.start` and `browser.navigate` and no history handler,
so the Browser panel offers an address field and a navigate action only. Back,
forward, and reload are deliberately absent rather than aliased onto
`browser.navigate` with the current address, which would claim history
authority the runtime does not have. Navigation carries the projected profile
generation and runtime revision, so a stale panel is refused by Python instead
of silently retargeted.

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

A frozen one-file helper announces the serving child PID rather than its
extraction parent. Swift supervises that announced PID, so crash recovery cannot
leave an orphan owning the socket. `BIRKIN_NATIVE_SOCKET` remains an explicit
user-managed attachment path; the production package journey exercises the
embedded helper with bridge overrides absent.

## Packaged QA seam

`BIRKIN_NATIVE_JOURNEY=1` opts the packaged executable into scripted release
QA; normal launches do not create a runner. The runner invokes the same Swift
control closures as the visible shell and waits on canonical app events. It has
no test transport, direct wire path, or alternate Python authority. Python
still decides every policy, approval, consent, terminal lease, product action,
and import.

The release harness removes bridge overrides and runs under an empty `HOME` and
sanitized `PATH`. A real existing-account provider probe must succeed through
the selected frozen helper and bundled browser tree. A separate composer action
must then receive the exact provider success marker before the remaining
product and reconnect journey can pass. Receipts, contentful screenshots, and
cleanup are machine-verified for both the clean app and mounted DMG.

## Packaging decision

`scripts/native/package_macos_app.sh` refuses a dirty source tree, then builds a
universal (`arm64` and `x86_64`) SwiftPM release binary and
architecture-specific frozen Python helpers. It also expands checksum-pinned
Chromium headless-shell and FFmpeg archives into signed browser trees.
`bridge-helper.json` records the clean revision and exact package version,
helper executable hashes, and browser tree hashes and byte sizes. The enclosing
app signature seals that manifest. Swift requires its generated version to
match the manifest, selects one architecture, and verifies the helper. The
bridge handshake independently requires the same exact product version, so a
developer override cannot bypass compatibility. Frozen Python verifies the
matching browser tree and sets Playwright only to that bundle path. The
resulting `com.birkin.native` app does not consult host Python, a repository, a
virtual environment, or a browser cache.

Signing is inside-out. When a Developer ID identity is available the script
uses it with hardened runtime and a timestamp. Otherwise it produces an
ad-hoc-signed development artifact with no hardened-runtime option or
entitlements. The script does not notarize either output; notarization,
stapling, and Gatekeeper assessment are separate credentialed public-release
gates.

App Sandbox is intentionally disabled in this package. The shipped architecture
uses PTYs, private local sockets, Accessibility, and Screen Recording facilities
outside the initial sandbox profile. Those operations remain constrained by
Python policy, typed capability and consent gates, peer authentication, and OS
privacy permissions rather than being misrepresented as sandbox-compatible.
