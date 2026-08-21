import Foundation
import Testing

@testable import BirkinNativeApp
import BirkinNativeProtocol
import BirkinNativeShell

@MainActor
private func readySession(of runtime: BirkinApplicationRuntime) -> NativeReadySession? {
    switch runtime.connectionState {
    case .ready(let value), .fallback(.ready(let value)): value
    default: nil
    }
}

@Suite("Packaged application terminal lease", .serialized)
struct BirkinApplicationTerminalLeaseTests {
    @MainActor
    @Test("the create receipt installs an ephemeral lease that drives mutation")
    func receiptLeaseDrivesTerminalMutation() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/birkin-app-terminal-\(UUID().uuidString)")
        let harness = try AppHarness.launch(
            root: root, mode: "--terminal", sessionID: "terminal-session", connections: 2
        )
        let socketPath = try #require(harness.socketPath)
        let events = RuntimeEventRecorder()
        let runtime = BirkinApplicationRuntime(socketPath: socketPath, emit: { events.record($0) })
        let controls = TerminalControlModel()
        defer {
            runtime.stop()
            harness.terminate()
            try? FileManager.default.removeItem(at: root)
        }
        var completed = 0
        func awaitCompletion(_ label: String) async throws {
            completed += 1
            let target = completed
            try await withTimeout(label) {
                try await events.wait(
                    for: "projection-event type=command.completed", occurrence: target
                )
            }
        }

        try await withTimeout("runtime start") { await runtime.start() }
        let ready = try #require(readySession(of: runtime))

        _ = controls.requestTerminal(
            cwd: root.path,
            expectedCursor: runtime.store.latestAppliedCursor ?? 0,
            sessionCapability: ready.sessionCapability,
            submit: { runtime.submit($0) }
        )
        try await awaitCompletion("terminal create")

        let opened = try #require(runtime.store.projection?.terminals.first)
        #expect(opened.lease != NativeRedaction.marker)
        #expect(opened.lease?.isEmpty == false)
        #expect(opened.readOnly == false)
        #expect(opened.state == "running")

        #expect(controls.sendInput(
            "printf lease-proof\n",
            terminal: opened,
            expectedCursor: runtime.store.latestAppliedCursor ?? 0,
            sessionCapability: ready.sessionCapability,
            submit: { runtime.submit($0) }
        ))
        try await awaitCompletion("terminal input")
        #expect(runtime.lastCommandError == nil)
        #expect(
            runtime.store.projection?.terminals.first?.screen.contains("lease-proof") == true,
            "screen=\(runtime.store.projection?.terminals.first?.screen ?? "nil")"
        )

        #expect(controls.interrupt(
            terminal: try #require(runtime.store.projection?.terminals.first),
            expectedCursor: runtime.store.latestAppliedCursor ?? 0,
            sessionCapability: ready.sessionCapability,
            submit: { runtime.submit($0) }
        ))
        try await awaitCompletion("terminal signal")
        #expect(runtime.lastCommandError == nil)

        let live = try #require(runtime.store.projection?.terminals.first)
        if live.state == "running" {
            #expect(controls.close(
                terminal: live,
                confirmed: true,
                expectedCursor: runtime.store.latestAppliedCursor ?? 0,
                sessionCapability: ready.sessionCapability,
                submit: { runtime.submit($0) }
            ))
            try await awaitCompletion("terminal close")
            #expect(runtime.lastCommandError == nil)
        }
        try await withTimeout("terminal exit") {
            try await events.wait(for: "projection-event type=terminal.exited")
        }
        let closed = try #require(runtime.store.projection?.terminals.first)
        #expect(closed.state == "exited")
        #expect(closed.lease == nil)
        #expect(closed.readOnly == true)
    }

    @MainActor
    @Test("a reconnect snapshot keeps the terminal read-only without a fresh lease")
    func reconnectSnapshotIsReadOnly() async throws {
        let root = URL(
            fileURLWithPath: "/private/tmp/birkin-app-terminal-replay-\(UUID().uuidString)"
        )
        let harness = try AppHarness.launch(
            root: root, mode: "--terminal", sessionID: "terminal-session", connections: 2
        )
        let socketPath = try #require(harness.socketPath)
        let events = RuntimeEventRecorder()
        let runtime = BirkinApplicationRuntime(socketPath: socketPath, emit: { events.record($0) })
        let controls = TerminalControlModel()
        defer {
            runtime.stop()
            harness.terminate()
            try? FileManager.default.removeItem(at: root)
        }

        try await withTimeout("runtime start") { await runtime.start() }
        let ready = try #require(readySession(of: runtime))
        _ = controls.requestTerminal(
            cwd: root.path,
            expectedCursor: runtime.store.latestAppliedCursor ?? 0,
            sessionCapability: ready.sessionCapability,
            submit: { runtime.submit($0) }
        )
        try await withTimeout("terminal opened") {
            try await events.wait(for: "projection-event type=terminal.opened")
        }
        runtime.stop()

        let reconnected = RuntimeEventRecorder()
        let second = BirkinApplicationRuntime(
            socketPath: socketPath, emit: { reconnected.record($0) }
        )
        defer { second.stop() }
        try await withTimeout("second runtime start") { await second.start() }

        let restored = try #require(second.store.projection?.terminals.first)
        #expect(restored.readOnly == true)
        #expect(restored.lease == nil)
        let secondSession = try #require(readySession(of: second))
        #expect(!TerminalControlModel().sendInput(
            "printf denied\n",
            terminal: restored,
            expectedCursor: second.store.latestAppliedCursor ?? 0,
            sessionCapability: secondSession.sessionCapability,
            submit: { second.submit($0) }
        ))
    }
}
