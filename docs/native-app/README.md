# Birkin Native macOS Application

Status: shipped repository contract. The repository builds a universal signed macOS application; credential-free builds are ad-hoc development artifacts rather than notarized public downloads.

Birkin's macOS application is a SwiftUI control surface over the existing Python runtime.

Python remains authoritative for:

- sessions and conversation execution
- memory and goals
- tools and terminal processes
- policy and approvals
- audit and recovery
- Browser Aside
- Computer Use
- Office document operations

SwiftUI renders versioned projections and sends explicit commands. It does not maintain a second database, make policy decisions, store provider credentials, attach personal browser profiles, or execute tools directly.

## Running the bridge

The application starts its own bridge process by running the shipped command:

```bash
birkin native-bridge serve [--transport uds|loopback] [--session-id ID] [--root DIR]
```

The command prints one JSON readiness line containing `event: "listening"`, the
transport, the process id, and the endpoint (`socket_path` for a Unix socket,
`discovery_path` for the loopback fallback). It serves connections until it
receives `SIGTERM` or `SIGINT`, then removes its endpoint and prints a final
`event: "stopped"` record.

Production selects `Contents/Helpers/<architecture>/birkin-native-bridge` from
the app-signature-sealed package manifest. Packaging refuses dirty source and
records its clean revision. Before launch, Swift requires the manifest package
version to equal its generated product version and verifies the selected
architecture and helper SHA-256. Every bridge must then return that same exact
version in `ready.server_version`. The frozen helper independently verifies the
selected browser tree under
`Contents/Resources/BrowserRuntimes/<architecture>` before setting
`PLAYWRIGHT_BROWSERS_PATH`; it never falls back to a host cache. The universal
package includes pinned arm64 and x86_64 Chromium headless-shell and FFmpeg
revisions.

`BIRKIN_NATIVE_BRIDGE_COMMAND` remains a developer override but cannot bypass
the exact product-version handshake. The app restarts only the serving PID the
helper announces, at most five times in sixty seconds, and terminates it on app
exit. `BIRKIN_NATIVE_SOCKET` attaches an already running user-managed bridge,
which the app never stops. Production operation requires no host Python,
repository checkout, virtual environment, or preinstalled browser runtime.

## Packaged release verification

`BIRKIN_NATIVE_JOURNEY=1` enables a release-QA seam that is otherwise disabled.
It drives the same action closures as the SwiftUI controls; it does not use a
test transport, a direct protocol client, or a separate Python authority. The
harness runs with an empty `HOME`, sanitized `PATH`, and bridge overrides
removed, while preserving access to the operator's existing provider account.

Acceptance first runs a real provider probe through the selected frozen helper
and verifies that the helper selected its bundled browser tree. The packaged
composer then requires a separate real provider-backed completion with the
exact success marker. Only then can the named session, approval and terminal,
Browser, Office, Computer Use status, Working Memory, jailed import,
restart/replay, and post-reconnect steps pass. The same verifier is applied to
the clean app and the mounted DMG. QA mode does not bypass Python policy,
approval, consent, lease, or redaction boundaries.

The packaging script signs nested executable code and the enclosing app
inside-out. It uses Developer ID signing and hardened runtime only when a
Developer ID identity is available. Otherwise it emits an ad-hoc-signed
development artifact with no hardened-runtime option or entitlements. The
script does not perform notarization; notarization, stapling, and Gatekeeper
assessment are separate credentialed public-release gates.

## Windows development preview

The repository also contains a .NET 8 WPF thin client at
`windows/BirkinNativeApp/`. Its implemented Phase 3 state is a development
preview, not a shipped or customer-ready release. One `BridgeSession` owns the
only authenticated loopback receive pump and shares one in-memory projection
store with the shell; Python remains the sole authority. The production-composed
deterministic WPF/real-bridge regressions are separate from the one real
existing-account Phase 3 Office proof documented under
`.omo/evidence/native-windows-20260824/remediation/w6/`.

On supported Windows builds, the Terminal is a typed WPF surface over the
Python-owned ConPTY/Windows Job backend; it has no client-side process fallback
or second authority. Browser remains projected-only. There is no Windows
installer/MSI, signing, updater, packaged app, or customer-ready release; those
remain Phases 4-5.

Stable public contracts:

- [Architecture](architecture.md)
- [Local protocol](protocol.md)
- [Security boundary](security.md)

The illustration in [`../assets/birkin-native-app-roadmap.png`](../assets/birkin-native-app-roadmap.png) shows the shipped product hierarchy. Python contracts define the actual policy categories and data schemas.
