import Darwin
import Foundation
import Testing

@testable import BirkinNativeApp
import BirkinNativeProtocol

@Suite("Packaged application runtime reconnect", .serialized)
struct BirkinApplicationReconnectIntegrationTests {
    @MainActor
    @Test("UI command submission reaches the bridge and updates projection state")
    func submitsUICommandOverLiveTransport() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/birkin-app-command-\(UUID().uuidString)")
        let harness = try AppHarness.launch(root: root)
        let socketPath = try #require(harness.socketPath)
        let events = RuntimeEventRecorder()
        let runtime = BirkinApplicationRuntime(socketPath: socketPath, emit: { events.record($0) })
        defer {
            runtime.stop()
            harness.terminate()
            try? FileManager.default.removeItem(at: root)
        }

        await runtime.start()
        try await withTimeout("office surface") { try await events.wait(for: "surface-applied name=office") }
        let session: NativeReadySession? = switch runtime.connectionState {
        case .ready(let value), .fallback(.ready(let value)): value
        default: nil
        }
        let ready = try #require(session)
        #expect(ready.currentSessionID == "runtime-advertised-session")
        #expect(runtime.store.projection?.sessionID == "runtime-advertised-session")
        #expect(runtime.store.surface(named: "browser_aside") != nil)
        #expect(runtime.store.surface(named: "computer_use") != nil)
        #expect(runtime.store.surface(named: "office") != nil)
        let before = runtime.store.projection?.conversation.count ?? 0
        runtime.submit(NativeCommandRequest(
            frameID: "ui-chat-frame", commandID: "ui-chat-command",
            expectedCursor: runtime.store.latestAppliedCursor ?? 0,
            commandType: "chat.send", payload: ["text": .string("Sent from the SwiftUI shell")],
            sessionCapability: ready.sessionCapability, viewID: "composer"
        ))

        try await withTimeout("wire receipt") { try await events.wait(for: "command-receipt") }
        try await withTimeout("projection update") {
            try await events.wait(for: "projection-event type=command.completed")
        }
        #expect(runtime.store.projection?.conversation.count == before + 2)
        #expect(runtime.lastCommandError == nil)
        #expect(ready.supportedCommands.contains("file.import"))

        let dropped = root.appendingPathComponent("drop.txt")
        try Data("drop through the app runtime".utf8).write(to: dropped)
        runtime.submit(NativeCommandRequest(
            frameID: "import-frame", commandID: "import-command",
            expectedCursor: runtime.store.latestAppliedCursor ?? 0,
            commandType: "file.import", payload: ["source_path": .string(dropped.path)],
            sessionCapability: ready.sessionCapability, viewID: "composer-drop"
        ))
        try await withTimeout("import receipt") {
            try await events.wait(for: "command-receipt id=import-frame")
        }
        let imports = root.appendingPathComponent("workspace-root/imports")
        let imported = try FileManager.default.contentsOfDirectory(at: imports, includingPropertiesForKeys: nil)
        #expect(imported.count == 1)
        #expect(try Data(contentsOf: imported[0]) == Data("drop through the app runtime".utf8))
    }

    @MainActor
    @Test("production sender binds caller-local view to negotiated connection scope")
    func productionSenderUsesNegotiatedScope() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/birkin-app-scope-\(UUID().uuidString)")
        let harness = try AppHarness.launch(root: root)
        let socketPath = try #require(harness.socketPath)
        let events = RuntimeEventRecorder()
        let runtime = BirkinApplicationRuntime(
            socketPath: socketPath,
            emit: { events.record($0) }
        )
        defer {
            runtime.stop()
            harness.terminate()
            try? FileManager.default.removeItem(at: root)
        }

        await runtime.start()
        let session: NativeReadySession? = switch runtime.connectionState {
        case .ready(let value), .fallback(.ready(let value)): value
        default: nil
        }
        let ready = try #require(session)
        runtime.submit(NativeCommandRequest(
            frameID: "scope-frame", commandID: "scope-command",
            expectedCursor: runtime.store.latestAppliedCursor ?? 0,
            commandType: "chat.send", payload: ["text": .string("Scoped command")],
            sessionCapability: ready.sessionCapability,
            viewID: "caller-spoof-must-not-cross-wire"
        ))

        try await withTimeout("scope response") {
            try await events.wait(for: "command-")
        }
        #expect(events.contains("command-receipt id=scope-frame"))
        #expect(!events.contains(
            "command-error id=scope-frame code=E_CAPABILITY_SCOPE"
        ))
    }

    @MainActor
    @Test("bridge loss reconnects and replays through the executable runtime")
    func reconnectsAfterBridgeRestart() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/birkin-app-reconnect-\(UUID().uuidString)")
        let first = try AppHarness.launch(root: root)
        let socketPath = try #require(first.socketPath)
        let clock = SignaledReconnectClock()
        let events = RuntimeEventRecorder()
        let runtime = BirkinApplicationRuntime(
            socketPath: socketPath,
            reconnectClock: clock,
            randomUnit: { 0.5 },
            emit: { events.record($0) }
        )
        defer {
            runtime.stop()
            first.terminate()
            try? FileManager.default.removeItem(at: root)
        }

        await runtime.start()
        #expect(runtime.store.latestAppliedCursor == 5)
        #expect(events.contains("connected"))

        first.killBridge()
        try await withTimeout("reconnect-scheduled") { try await events.wait(for: "reconnect-scheduled") }
        try await withTimeout("scheduler sleep") { try await clock.waitUntilSleeping() }
        let second = try AppHarness.launch(root: root)
        defer { second.terminate() }
        clock.resume()

        try await withTimeout("replayed") { try await events.wait(for: "replayed") }
        #expect(runtime.store.latestAppliedCursor == 5)
        #expect(events.contains("reconnect-attempt"))
        #expect(events.contains("replayed"))

        let session: NativeReadySession? = switch runtime.connectionState {
        case .ready(let value), .fallback(.ready(let value)): value
        default: nil
        }
        let ready = try #require(session)
        #expect(runtime.store.projection?.composer.canSend == true)
        try await runtime.submitAwaitingTransport(NativeCommandRequest(
            frameID: "post-reconnect-frame", commandID: "post-reconnect-command",
            expectedCursor: runtime.store.latestAppliedCursor ?? 0,
            commandType: "chat.send", payload: ["text": .string("Command after reconnect")],
            sessionCapability: ready.sessionCapability, viewID: "composer"
        ))
        try await withTimeout("post reconnect receipt") {
            try await events.wait(for: "command-receipt id=post-reconnect-frame")
        }
        try await withTimeout("post reconnect outcome") {
            try await events.wait(for: "projection-event type=command.completed")
        }
        #expect(events.contains(
            "projection-event type=command.completed command_id=post-reconnect-command"
        ))

        runtime.stop()
        try await withTimeout("reconnect bridge cleanup", seconds: 60) {
            await Task.detached { second.process.waitUntilExit() }.value
        }
        #expect(!second.process.isRunning)
    }
}
