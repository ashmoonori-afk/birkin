import Darwin
import Foundation
import Testing

@testable import BirkinNativeApp
import BirkinNativeProtocol
import BirkinNativeShell

@Suite("Packaged application owned bridge", .serialized)
struct BirkinApplicationOwnedBridgeTests {
    private static func configuration(root: URL) -> OwnedBridgeConfiguration {
        OwnedBridgeConfiguration(
            executable: AppHarness.repository
                .appendingPathComponent(".venv/bin/python3").path,
            leadingArguments: ["-m", "birkin"],
            serveOptions: [
                "--root", root.path,
                "--session-id", "owned-bridge-session",
            ]
        )
    }

    @MainActor
    @Test("a typed first-run helper failure is visible and Retry reconnects after restore")
    func firstRunFailureRetry() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/bk-retry-\(UUID().uuidString)")
        let events = RuntimeEventRecorder()
        var restored = false
        let runtime = BirkinApplicationRuntime(
            socketPath: nil,
            ownedBridge: nil,
            ownedBridgeFailure: OwnedBridgeDiscoveryError(.helperMissing),
            ownedBridgeResolver: { restored ? Self.configuration(root: root) : nil },
            emit: { events.record($0) }
        )
        defer {
            runtime.stop()
            try? FileManager.default.removeItem(at: root)
        }

        await runtime.start()
        guard case .failed(let reason) = runtime.connectionState else {
            Issue.record("missing helper failure was not visible")
            return
        }
        #expect(reason.hasPrefix("code=embedded_helper_missing"))
        #expect(ConnectionPresentation(state: runtime.connectionState).actionLabel == "Retry")

        restored = true
        let connected = Task { try await events.wait(for: "connected transport=uds") }
        await runtime.retryBridge()
        try await withTimeout("retry connects") { try await connected.value }
        #expect(runtime.store.projection?.sessionID == "owned-bridge-session")
        print("B4 RETRY code=embedded_helper_missing restored=true connected=uds")
    }

    @MainActor
    @Test("the application starts, uses, restarts, and stops its own bridge")
    func ownsItsBridgeLifecycle() async throws {
        // A Unix socket path is platform bounded, so this root stays short.
        let root = URL(fileURLWithPath: "/private/tmp/bk-owned-\(UUID().uuidString)")
        let events = RuntimeEventRecorder()
        let runtime = BirkinApplicationRuntime(
            socketPath: nil,
            ownedBridge: Self.configuration(root: root),
            emit: { events.record($0) }
        )
        defer {
            runtime.stop()
            try? FileManager.default.removeItem(at: root)
        }

        try await withTimeout("owned bridge start", seconds: 60) { await runtime.start() }

        #expect(events.contains("bridge-started kind=owned"))
        #expect(events.contains("connected transport=uds"), "log=\(events.recorded())")
        let firstPID = try #require(runtime.ownedBridgeProcessIdentifier)
        #expect(runtime.store.projection?.sessionID == "owned-bridge-session")

        _ = kill(firstPID, SIGKILL)
        try await withTimeout("owned bridge restart", seconds: 60) {
            try await events.wait(for: "bridge-restarted kind=owned")
        }
        let secondPID = try #require(runtime.ownedBridgeProcessIdentifier)
        #expect(secondPID != firstPID)

        try await withTimeout("reconnect after restart", seconds: 60) {
            try await events.wait(for: "replayed")
        }
        #expect(runtime.store.projection != nil)

        runtime.stop()
        #expect(runtime.ownedBridgeProcessIdentifier == nil)
        try await withTimeout("owned bridge exit", seconds: 30) {
            while kill(secondPID, 0) == 0 {
                try await Task.sleep(for: .milliseconds(20))
            }
        }
    }

    @MainActor
    @Test("New Session creates the advertised canonical Python session")
    func createsCanonicalSession() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/bk-session-\(UUID().uuidString)")
        let events = RuntimeEventRecorder()
        let runtime = BirkinApplicationRuntime(
            socketPath: nil,
            ownedBridge: Self.configuration(root: root),
            emit: { events.record($0) }
        )
        defer {
            runtime.stop()
            try? FileManager.default.removeItem(at: root)
        }

        try await withTimeout("owned bridge start", seconds: 60) { await runtime.start() }
        let session: NativeReadySession? = switch runtime.connectionState {
        case .ready(let value), .fallback(.ready(let value)): value
        default: nil
        }
        let ready = try #require(session)
        #expect(ready.supportedCommands.contains("session.create"))
        let request = runtime.command(for: .newSession, session: ready)
        guard case .string(let createdSessionID) = request.payload["session_id"] else {
            Issue.record("session.create did not carry a session_id")
            return
        }

        runtime.submit(request)
        try await withTimeout("session create receipt") {
            try await events.wait(for: "command-receipt id=\(request.frameID)")
        }
        try await withTimeout("session created event") {
            try await events.wait(for: "projection-event type=session.created")
        }
        #expect(events.contains(
            "projection-event type=session.created command_id=\(request.commandID) "
                + "subject_session_id=\(createdSessionID)"
        ))
        try await withTimeout("session create outcome") {
            try await events.wait(
                for: "projection-event type=command.completed command_id=\(request.commandID)"
            )
        }

        var isDirectory: ObjCBool = false
        let createdPath = root.appendingPathComponent("workspace/\(createdSessionID)").path
        #expect(FileManager.default.fileExists(
            atPath: createdPath, isDirectory: &isDirectory
        ))
        #expect(isDirectory.boolValue)
    }

    @MainActor
    @Test("an externally provided endpoint is used without starting a bridge")
    func externalEndpointIsNeverOwned() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/bk-external-\(UUID().uuidString)")
        let harness = try AppHarness.launch(root: root)
        let socketPath = try #require(harness.socketPath)
        let events = RuntimeEventRecorder()
        let runtime = BirkinApplicationRuntime(
            socketPath: socketPath,
            ownedBridge: Self.configuration(root: root.appendingPathComponent("owned")),
            emit: { events.record($0) }
        )
        defer {
            runtime.stop()
            harness.terminate()
            try? FileManager.default.removeItem(at: root)
        }

        try await withTimeout("external start", seconds: 30) { await runtime.start() }
        try await withTimeout("external connected", seconds: 30) {
            try await events.wait(for: "connected transport=uds")
        }

        #expect(events.contains("bridge-attached kind=external"))
        #expect(!events.contains("bridge-started kind=owned"))
        #expect(runtime.ownedBridgeProcessIdentifier == nil)
        #expect(harness.process.isRunning)

        runtime.stop()
        try await withTimeout("external bridge cleanup", seconds: 60) {
            await Task.detached { harness.process.waitUntilExit() }.value
        }
        #expect(!harness.process.isRunning)
    }
}
