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
    public static let browserURLKey = "BIRKIN_NATIVE_JOURNEY_BROWSER_URL"

    public let evidenceRoot: URL
    public let workspaceRoot: URL
    public let browserURL: URL

    public init(evidenceRoot: URL, workspaceRoot: URL, browserURL: URL) {
        self.evidenceRoot = evidenceRoot
        self.workspaceRoot = workspaceRoot
        self.browserURL = browserURL
    }

    public static func discovered(
        in environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> PackagedJourneyConfiguration? {
        guard environment[enabledKey] == "1",
              let evidence = environment[evidenceKey], !evidence.isEmpty,
              let workspace = environment[workspaceKey], !workspace.isEmpty,
              let browserAddress = environment[browserURLKey],
              let browserURL = URL(string: browserAddress),
              ["http", "https"].contains(browserURL.scheme?.lowercased()) else {
            return nil
        }
        return PackagedJourneyConfiguration(
            evidenceRoot: URL(fileURLWithPath: evidence),
            workspaceRoot: URL(fileURLWithPath: workspace),
            browserURL: browserURL
        )
    }
}

/// One recorded journey step.
struct JourneyStep: Encodable {
    let name: String
    let state: String
    let surface: String
    let succeeded: Bool
    let detail: String
    let screenshot: String?
    let capture: PackagedWindowCaptureReceipt?
}

enum JourneyEvidenceRedactor {
    static func redact(_ value: String) -> String {
        let marker = NativeRedaction.marker
        var redacted = value.replacingOccurrences(
            of: #"(?i)"?\b(authorization|access_token|refresh_token|api_key|session_capability|capability|token|secret|password|reference|owner|lease|approval_id)"?\s*[:=]\s*(?:"[^"]*"|'[^']*'|(?:Basic|Bearer)\s+[A-Za-z0-9._~+/=-]+|[^\s,}\]]+)"#,
            with: "$1=\(marker)",
            options: .regularExpression
        )
        redacted = redacted.replacingOccurrences(
            of: #"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"#,
            with: "Bearer \(marker)",
            options: .regularExpression
        )
        return redacted.replacingOccurrences(
            of: #"\bsk-[A-Za-z0-9_-]{8,}"#,
            with: marker,
            options: .regularExpression
        )
    }
}

/// Awaits application events by prefix without polling or sleeping.
///
/// Only a QA run owns one of these. Retention is bounded, while monotonic
/// counts for the journey's fixed wait patterns preserve absolute occurrences
/// after matching evidence leaves the retained window.
final class JourneyEventLog: @unchecked Sendable {
    /// The ceiling on retained lines for one QA run.
    static let retainedLineLimit = 2048

    private struct MatchSeries: Hashable {
        let prefixes: [String]

        init(_ prefixes: [String]) {
            self.prefixes = prefixes.sorted()
        }

        func matches(_ line: String) -> Bool {
            prefixes.contains { line.hasPrefix($0) }
        }
    }

    private struct Waiter {
        let id: UUID
        let series: MatchSeries
        let occurrence: Int
        let continuation: CheckedContinuation<Void, Error>
    }

    private let lock = NSLock()
    private var lines: [String] = []
    private var occurrences: [MatchSeries: Int] = [:]
    private var waiters: [Waiter] = []

    func record(_ line: String) {
        let ready: [CheckedContinuation<Void, Error>] = lock.withLock {
            lines.append(line)
            if lines.count > Self.retainedLineLimit {
                lines.removeFirst(lines.count - Self.retainedLineLimit)
            }
            for series in Array(occurrences.keys) where series.matches(line) {
                occurrences[series, default: 0] += 1
            }
            var resumed: [CheckedContinuation<Void, Error>] = []
            var pending: [Waiter] = []
            for waiter in waiters {
                if occurrences[waiter.series, default: 0] >= waiter.occurrence {
                    resumed.append(waiter.continuation)
                } else {
                    pending.append(waiter)
                }
            }
            waiters = pending
            return resumed
        }
        ready.forEach { $0.resume() }
    }

    func recorded() -> [String] { lock.withLock { lines } }

    func persisted() -> [String] {
        recorded().map(JourneyEvidenceRedactor.redact)
    }

    private func count(of series: MatchSeries) -> Int {
        lines.filter(series.matches).count
    }

    func wait(forAnyOf prefixes: [String], occurrence: Int) async throws {
        try await wait(for: prefixes, occurrence: occurrence)
    }

    func wait(
        for prefix: String,
        occurrence: Int = 1,
        onRegistered: @Sendable () -> Void = {}
    ) async throws {
        try await wait(
            for: [prefix], occurrence: occurrence, onRegistered: onRegistered
        )
    }

    private func wait(
        for prefixes: [String],
        occurrence: Int,
        onRegistered: @Sendable () -> Void = {}
    ) async throws {
        let id = UUID()
        let series = MatchSeries(prefixes)
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                let satisfied: Bool = lock.withLock {
                    let seen = occurrences[series] ?? count(of: series)
                    occurrences[series] = seen
                    if seen >= occurrence { return true }
                    waiters.append(Waiter(
                        id: id, series: series, occurrence: occurrence,
                        continuation: continuation
                    ))
                    return false
                }
                if satisfied {
                    continuation.resume()
                } else {
                    onRegistered()
                }
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
