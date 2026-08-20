import Darwin
import Foundation
import Testing

@testable import BirkinNativeApp
import BirkinNativeProtocol

@Suite("Packaged application runtime reconnect")
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
            try await events.wait(for: "projection-event type=message.assistant.completed")
        }
        #expect(runtime.store.projection?.conversation.count == before + 2)
        #expect(runtime.lastCommandError == nil)
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
    }
}

private final class RuntimeEventRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [String] = []
    private var waiters: [(String, CheckedContinuation<Void, Error>)] = []

    func record(_ value: String) {
        let ready: [CheckedContinuation<Void, Error>] = lock.withLock {
            values.append(value)
            let matches = waiters.filter { value.hasPrefix($0.0) }
            waiters.removeAll { value.hasPrefix($0.0) }
            return matches.map(\.1)
        }
        ready.forEach { $0.resume() }
    }

    func contains(_ prefix: String) -> Bool {
        lock.withLock { values.contains { $0.hasPrefix(prefix) } }
    }

    func wait(for prefix: String) async throws {
        if contains(prefix) { return }
        try await withCheckedThrowingContinuation { continuation in
            lock.withLock { waiters.append((prefix, continuation)) }
        }
    }
}

private final class SignaledReconnectClock: NativeReconnectClock, @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Void, Error>?
    private var sleepingWaiters: [CheckedContinuation<Void, Error>] = []

    func sleep(for _: TimeInterval) async throws {
        try await withCheckedThrowingContinuation { continuation in
            let waiters = lock.withLock {
                self.continuation = continuation
                let pending = sleepingWaiters
                sleepingWaiters.removeAll()
                return pending
            }
            waiters.forEach { $0.resume() }
        }
    }

    func waitUntilSleeping() async throws {
        let alreadySleeping = lock.withLock { continuation != nil }
        if alreadySleeping { return }
        try await withCheckedThrowingContinuation { continuation in
            lock.withLock { sleepingWaiters.append(continuation) }
        }
    }

    func resume() {
        let pending = lock.withLock {
            let pending = continuation
            continuation = nil
            return pending
        }
        pending?.resume()
    }
}

private final class AppHarness: @unchecked Sendable {
    let process: Process
    let root: URL
    let socketPath: String?

    private init(process: Process, root: URL, socketPath: String?) {
        self.process = process
        self.root = root
        self.socketPath = socketPath
    }

    static func launch(root: URL) throws -> AppHarness {
        let package = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent()
        let repository = package.deletingLastPathComponent().deletingLastPathComponent()
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let process = Process()
        let stdout = Pipe()
        process.executableURL = repository.appendingPathComponent(".venv/bin/python3")
        process.arguments = [
            "scripts/native/swift_transport_harness.py", "--transport", "uds",
            "--root", root.path, "--j1-fixture",
            "--session-id", "runtime-advertised-session",
        ]
        process.currentDirectoryURL = repository
        process.standardOutput = stdout
        process.standardError = FileHandle.standardError
        try process.run()
        let line = try readLine(from: stdout.fileHandleForReading, timeout: 10)
        guard let data = line.data(using: .utf8),
              let record = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              record["event"] as? String == "listening"
        else {
            process.terminate()
            throw AppReconnectTestError.malformedReadiness
        }
        return AppHarness(
            process: process, root: root, socketPath: record["socket_path"] as? String
        )
    }

    func killBridge() {
        _ = kill(process.processIdentifier, SIGKILL)
        process.waitUntilExit()
    }

    func terminate() {
        guard process.isRunning else { return }
        process.terminate()
        process.waitUntilExit()
    }

    private static func readLine(from handle: FileHandle, timeout: TimeInterval) throws -> String {
        let bytes = LockedBytes()
        let ready = DispatchSemaphore(value: 0)
        DispatchQueue.global().async {
            while true {
                let byte = handle.readData(ofLength: 1)
                if byte.isEmpty || byte == Data([0x0a]) { break }
                bytes.append(byte)
            }
            ready.signal()
        }
        guard ready.wait(timeout: .now() + timeout) == .success else {
            throw AppReconnectTestError.timeout("harness readiness")
        }
        return bytes.text()
    }
}

private final class LockedBytes: @unchecked Sendable {
    private let lock = NSLock()
    private var bytes = Data()

    func append(_ data: Data) { lock.withLock { bytes.append(data) } }
    func text() -> String { lock.withLock { String(decoding: bytes, as: UTF8.self) } }
}

private func withTimeout<T: Sendable>(
    _ label: String,
    operation: @escaping @Sendable () async throws -> T
) async throws -> T {
    try await withThrowingTaskGroup(of: T.self) { group in
        group.addTask { try await operation() }
        group.addTask {
            try await Task.sleep(for: .seconds(10))
            throw AppReconnectTestError.timeout(label)
        }
        let result = try await group.next()!
        group.cancelAll()
        return result
    }
}

private enum AppReconnectTestError: Error {
    case timeout(String)
    case malformedReadiness
}
