import AppKit
import Foundation

import BirkinNativeProtocol
import BirkinNativeShell

/// Scripted QA mode for the packaged application.
///
/// It is disabled unless `BIRKIN_NATIVE_JOURNEY=1` is set, and it drives the
/// same action closures the shell's controls call: no test transport, no
/// direct wire access, no Python invocation of its own.
public struct PackagedJourneyConfiguration: Sendable {
    public static let enabledKey = "BIRKIN_NATIVE_JOURNEY"
    public static let evidenceKey = "BIRKIN_NATIVE_JOURNEY_EVIDENCE"
    public static let workspaceKey = "BIRKIN_NATIVE_JOURNEY_WORKSPACE"

    public let evidenceRoot: URL
    public let workspaceRoot: URL

    public static func discovered(
        in environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> PackagedJourneyConfiguration? {
        guard environment[enabledKey] == "1",
              let evidence = environment[evidenceKey], !evidence.isEmpty,
              let workspace = environment[workspaceKey], !workspace.isEmpty else {
            return nil
        }
        return PackagedJourneyConfiguration(
            evidenceRoot: URL(fileURLWithPath: evidence),
            workspaceRoot: URL(fileURLWithPath: workspace)
        )
    }
}

/// One recorded journey step.
struct JourneyStep: Encodable {
    let name: String
    let succeeded: Bool
    let detail: String
    let screenshot: String?
}

/// Awaits application events by prefix without polling or sleeping.
final class JourneyEventLog: @unchecked Sendable {
    private struct Waiter {
        let id: UUID
        let prefixes: [String]
        let occurrence: Int
        let continuation: CheckedContinuation<Void, Error>
    }

    private let lock = NSLock()
    private var lines: [String] = []
    private var waiters: [Waiter] = []

    func record(_ line: String) {
        let ready: [CheckedContinuation<Void, Error>] = lock.withLock {
            lines.append(line)
            let satisfied = waiters.filter { $0.occurrence <= count(of: $0.prefixes) }
            waiters.removeAll { waiter in satisfied.contains { $0.id == waiter.id } }
            return satisfied.map(\.continuation)
        }
        ready.forEach { $0.resume() }
    }

    func recorded() -> [String] { lock.withLock { lines } }

    private func count(of prefixes: [String]) -> Int {
        lines.filter { line in prefixes.contains { line.hasPrefix($0) } }.count
    }

    func wait(forAnyOf prefixes: [String], occurrence: Int) async throws {
        try await wait(for: prefixes, occurrence: occurrence)
    }

    func wait(for prefix: String, occurrence: Int = 1) async throws {
        try await wait(for: [prefix], occurrence: occurrence)
    }

    private func wait(for prefixes: [String], occurrence: Int) async throws {
        let id = UUID()
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                let satisfied: Bool = lock.withLock {
                    if count(of: prefixes) >= occurrence { return true }
                    waiters.append(Waiter(
                        id: id, prefixes: prefixes, occurrence: occurrence,
                        continuation: continuation
                    ))
                    return false
                }
                if satisfied { continuation.resume() }
            }
        } onCancel: {
            let cancelled = lock.withLock { () -> Waiter? in
                guard let index = waiters.firstIndex(where: { $0.id == id }) else {
                    return nil
                }
                return waiters.remove(at: index)
            }
            cancelled?.continuation.resume(throwing: CancellationError())
        }
    }
}

enum JourneyError: Error {
    case timedOut(String)
    case refused(String)
}

/// Awaits an event-signalled condition under a bounded budget.
func journeyDeadline<T: Sendable>(
    _ label: String,
    seconds: Int = 90,
    operation: @escaping @Sendable () async throws -> T
) async throws -> T {
    try await withThrowingTaskGroup(of: T.self) { group in
        group.addTask { try await operation() }
        group.addTask {
            try await Task.sleep(for: .seconds(seconds))
            throw JourneyError.timedOut(label)
        }
        let result = try await group.next()!
        group.cancelAll()
        return result
    }
}
