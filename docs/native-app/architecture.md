# Native Application Architecture

Status: planned architecture contract. Not yet implemented.

## Thin-shell boundary

The macOS application has three responsibilities:

1. connect to the local Python bridge,
2. render Python-provided snapshots and events,
3. send explicit versioned commands.

The Python runtime remains the only authority for state, policy, execution, audit, and recovery.

## Components

### Python

The native bridge:

- accepts a private Unix socket connection, falling back to authenticated private loopback only when the socket is unavailable or diagnostics explicitly request it
- negotiates protocol version and limits
- authenticates the local client
- exposes registered workspace command capabilities
- forwards canonical workspace snapshots, events, commands, and receipts
- emits redacted Browser Aside, Computer Use, Office, Working Memory, and Terminal projections

Existing runtime modules do not depend on the native bridge.

### Swift

The macOS application contains:

- strict protocol and transport layers
- an ephemeral projection store
- SwiftUI views
- bounded redacted diagnostics
- menu bar, notification, drag-and-drop, accessibility, and optional voice integration

Swift may persist presentation preferences such as window geometry and panel layout. It does not persist session content, approvals, capabilities, receipts, or execution state.

## Product surfaces

- Sessions and templates
- Conversation and composer
- Working Memory
- Python-owned Terminal
- Approvals and Activity
- Browser Aside
- Computer Use status and consent
- Office create and open
- connection and restart recovery

Every enabled control corresponds to a capability advertised by Python. An unavailable capability renders an explicit reason rather than a placeholder implementation.

## Recovery

Workspace events are cursor-based and durable. Reconnection resumes after the last applied cursor when the Python instance is unchanged. A new Python instance causes a full replay.

Commands use stable identifiers for idempotent recovery. Restart-interrupted commands are rendered as canonical failures and require a new explicit retry.
