import Darwin
import Foundation

import BirkinNativeProtocol

enum AppRuntimeTestError: Error {
    case timeout(String)
    case malformedReadiness
}

/// Records the runtime's event log and lets a test await one line by prefix.
final class RuntimeEventRecorder: @unchecked Sendable {
    private struct Waiter {
        let id: UUID
        let prefix: String
        let occurrence: Int
        let continuation: CheckedContinuation<Void, Error>
    }

    private let lock = NSLock()
    private var values: [String] = []
    private var waiters: [Waiter] = []

    func record(_ value: String) {
        let ready: [CheckedContinuation<Void, Error>] = lock.withLock {
            values.append(value)
            let satisfied = waiters.filter { $0.occurrence <= count(of: $0.prefix) }
            waiters.removeAll { waiter in satisfied.contains { $0.id == waiter.id } }
            return satisfied.map(\.continuation)
        }
        ready.forEach { $0.resume() }
    }

    private func count(of prefix: String) -> Int {
        values.filter { $0.hasPrefix(prefix) }.count
    }

    func contains(_ prefix: String) -> Bool {
        lock.withLock { values.contains { $0.hasPrefix(prefix) } }
    }

    func recorded() -> [String] {
        lock.withLock { values }
    }

    /// Await one recorded line by prefix. Cancellation resumes the waiter, so a
    /// bounded timeout around this call fails the test instead of deadlocking.
    func wait(for prefix: String, occurrence: Int = 1) async throws {
        let id = UUID()
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                let alreadyRecorded: Bool = lock.withLock {
                    if count(of: prefix) >= occurrence { return true }
                    waiters.append(Waiter(
                        id: id, prefix: prefix, occurrence: occurrence,
                        continuation: continuation
                    ))
                    return false
                }
                if alreadyRecorded { continuation.resume() }
            }
        } onCancel: {
            let cancelled = lock.withLock { () -> Waiter? in
                guard let index = waiters.firstIndex(where: { $0.id == id }) else { return nil }
                return waiters.remove(at: index)
            }
            cancelled?.continuation.resume(throwing: CancellationError())
        }
    }
}

/// A reconnect clock that parks until a test explicitly resumes it.
final class SignaledReconnectClock: NativeReconnectClock, @unchecked Sendable {
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

/// A real Python bridge process serving the app runtime under test.
final class AppHarness: @unchecked Sendable {
    let process: Process
    let root: URL
    let socketPath: String?

    private init(process: Process, root: URL, socketPath: String?) {
        self.process = process
        self.root = root
        self.socketPath = socketPath
    }

    static func launch(
        root: URL,
        mode: String = "--j1-fixture",
        sessionID: String = "runtime-advertised-session",
        connections: Int = 1,
        environment: [String: String] = [:]
    ) throws -> AppHarness {
        let repository = Self.repository
        try FileManager.default.createDirectory(
            at: root, withIntermediateDirectories: true
        )
        let process = Process()
        let stdout = Pipe()
        process.executableURL = repository.appendingPathComponent(".venv/bin/python3")
        process.arguments = [
            "scripts/native/swift_transport_harness.py", "--transport", "uds",
            "--root", root.path, mode,
            "--connections", String(connections),
            "--session-id", sessionID,
        ]
        process.currentDirectoryURL = repository
        process.environment = ProcessInfo.processInfo.environment.merging(
            environment, uniquingKeysWith: { _, override in override }
        )
        process.standardOutput = stdout
        process.standardError = FileHandle.standardError
        try process.run()
        let line = try readLine(from: stdout.fileHandleForReading, timeout: 20)
        guard let data = line.data(using: .utf8),
              let record = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              record["event"] as? String == "listening"
        else {
            _ = kill(process.processIdentifier, SIGKILL)
            process.waitUntilExit()
            throw AppRuntimeTestError.malformedReadiness
        }
        return AppHarness(
            process: process, root: root, socketPath: record["socket_path"] as? String
        )
    }

    static var repository: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent()
    }

    func killBridge() {
        _ = kill(process.processIdentifier, SIGKILL)
        process.waitUntilExit()
    }

    func terminate() {
        guard process.isRunning else { return }
        _ = kill(process.processIdentifier, SIGKILL)
        process.waitUntilExit()
    }

    private static func readLine(
        from handle: FileHandle, timeout: TimeInterval
    ) throws -> String {
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
            throw AppRuntimeTestError.timeout("harness readiness")
        }
        return bytes.text()
    }
}

final class LockedBytes: @unchecked Sendable {
    private let lock = NSLock()
    private var bytes = Data()

    func append(_ data: Data) { lock.withLock { bytes.append(data) } }
    func text() -> String { lock.withLock { String(decoding: bytes, as: UTF8.self) } }
}

/// Await an event-signalled condition with a bound generous enough that a
/// loaded machine cannot fail it, and small enough to end a hung run.
func withTimeout<T: Sendable>(
    _ label: String,
    seconds: Int = 45,
    operation: @escaping @Sendable () async throws -> T
) async throws -> T {
    try await withThrowingTaskGroup(of: T.self) { group in
        group.addTask { try await operation() }
        group.addTask {
            try await Task.sleep(for: .seconds(seconds))
            throw AppRuntimeTestError.timeout(label)
        }
        let result = try await group.next()!
        group.cancelAll()
        return result
    }
}
