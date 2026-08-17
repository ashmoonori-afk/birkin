# Birkin Native macOS Application

Status: planned contract. The macOS application is not yet released. This document defines the interface it will expose, not current behavior.

Birkin's planned macOS application is a SwiftUI control surface over the existing Python runtime.

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

Stable public contracts:

- [Architecture](architecture.md)
- [Local protocol](protocol.md)
- [Security boundary](security.md)

The illustration in [`../assets/birkin-native-app-roadmap.png`](../assets/birkin-native-app-roadmap.png) shows the intended product hierarchy. Python contracts define the actual policy categories and data schemas.
