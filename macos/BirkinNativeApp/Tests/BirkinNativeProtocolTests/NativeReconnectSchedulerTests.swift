import Foundation
import Testing

@testable import BirkinNativeProtocol

@Suite("Native reconnect scheduling")
struct NativeReconnectSchedulerTests {
    @Test("disconnect events trigger deterministic bounded exponential backoff")
    func eventDrivenDeterministicBackoff() async {
        let first = LockedSequence([0.0, 0.25, 0.75, 1.0])
        let second = LockedSequence([0.0, 0.25, 0.75, 1.0])
        let firstClock = RecordingReconnectClock()
        let secondClock = RecordingReconnectClock()
        let firstAttempts = AttemptOutcomes([false, false, false, true])
        let secondAttempts = AttemptOutcomes([false, false, false, true])
        let policy = NativeReconnectPolicy(
            initialDelay: 1,
            maximumDelay: 5,
            jitterFraction: 0.2
        )
        let firstScheduler = NativeReconnectScheduler(
            policy: policy,
            clock: firstClock,
            randomUnit: { first.next() },
            reconnect: { await firstAttempts.next() }
        )
        let secondScheduler = NativeReconnectScheduler(
            policy: policy,
            clock: secondClock,
            randomUnit: { second.next() },
            reconnect: { await secondAttempts.next() }
        )

        #expect(firstClock.delays.isEmpty)
        await firstScheduler.disconnected()
        #expect(secondClock.delays.isEmpty)
        await secondScheduler.disconnected()

        #expect(firstClock.delays == secondClock.delays)
        #expect(firstClock.delays == [0.8, 1.8, 4.4, 5.0])
        #expect(firstClock.delays.allSatisfy { $0 <= 5 })
    }
}

private final class RecordingReconnectClock: NativeReconnectClock, @unchecked Sendable {
    private let lock = NSLock()
    private var storage: [TimeInterval] = []

    var delays: [TimeInterval] {
        lock.withLock { storage }
    }

    func sleep(for delay: TimeInterval) async throws {
        lock.withLock { storage.append(delay) }
    }
}

private final class LockedSequence: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [Double]

    init(_ values: [Double]) {
        self.values = values
    }

    func next() -> Double {
        lock.withLock { values.removeFirst() }
    }
}

private final class AttemptOutcomes: @unchecked Sendable {
    private let lock = NSLock()
    private var outcomes: [Bool]

    init(_ outcomes: [Bool]) {
        self.outcomes = outcomes
    }

    func next() async -> Bool {
        lock.withLock { outcomes.removeFirst() }
    }
}
