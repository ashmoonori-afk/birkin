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

The app locates that command through `BIRKIN_NATIVE_BRIDGE_COMMAND` or the
executable bundled beside it, restarts it at most five times in sixty seconds,
and terminates it when the app exits. Setting `BIRKIN_NATIVE_SOCKET` attaches an
already running bridge, which the app treats as user-managed and never stops.

Stable public contracts:

- [Architecture](architecture.md)
- [Local protocol](protocol.md)
- [Security boundary](security.md)

The illustration in [`../assets/birkin-native-app-roadmap.png`](../assets/birkin-native-app-roadmap.png) shows the shipped product hierarchy. Python contracts define the actual policy categories and data schemas.
