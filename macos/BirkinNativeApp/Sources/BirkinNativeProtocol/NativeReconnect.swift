import Foundation

public protocol NativeReconnectClock: Sendable {
    func sleep(for delay: TimeInterval) async throws
}

public struct NativeContinuousReconnectClock: NativeReconnectClock {
    public init() {}

    public func sleep(for delay: TimeInterval) async throws {
        try await Task.sleep(for: .seconds(delay))
    }
}

public struct NativeReconnectPolicy: Equatable, Sendable {
    public let initialDelay: TimeInterval
    public let maximumDelay: TimeInterval
    public let jitterFraction: Double

    public init(
        initialDelay: TimeInterval = 0.5,
        maximumDelay: TimeInterval = 30,
        jitterFraction: Double = 0.2
    ) {
        precondition(initialDelay > 0)
        precondition(maximumDelay >= initialDelay)
        precondition((0...1).contains(jitterFraction))
        self.initialDelay = initialDelay
        self.maximumDelay = maximumDelay
        self.jitterFraction = jitterFraction
    }

    func delay(attempt: Int, randomUnit: Double) -> TimeInterval {
        var exponential = initialDelay
        for _ in 0..<attempt {
            exponential = min(maximumDelay, exponential * 2)
        }
        let boundedUnit = min(1, max(0, randomUnit))
        let jitterMultiplier = 1 - jitterFraction + (2 * jitterFraction * boundedUnit)
        return min(maximumDelay, exponential * jitterMultiplier)
    }
}

/// Runs only in response to a disconnect event. The injected clock and random
/// source make the complete retry schedule deterministic in tests.
public actor NativeReconnectScheduler {
    public typealias RandomUnit = @Sendable () -> Double
    public typealias Reconnect = @Sendable () async -> Bool

    private let policy: NativeReconnectPolicy
    private let clock: any NativeReconnectClock
    private let randomUnit: RandomUnit
    private let reconnect: Reconnect
    private var reconnecting = false

    public init(
        policy: NativeReconnectPolicy = NativeReconnectPolicy(),
        clock: any NativeReconnectClock = NativeContinuousReconnectClock(),
        randomUnit: @escaping RandomUnit = { Double.random(in: 0...1) },
        reconnect: @escaping Reconnect
    ) {
        self.policy = policy
        self.clock = clock
        self.randomUnit = randomUnit
        self.reconnect = reconnect
    }

    public func disconnected() async {
        guard !reconnecting else { return }
        reconnecting = true
        defer { reconnecting = false }

        var attempt = 0
        while !Task.isCancelled {
            let delay = policy.delay(attempt: attempt, randomUnit: randomUnit())
            do {
                try await clock.sleep(for: delay)
            } catch {
                return
            }
            if await reconnect() {
                return
            }
            attempt += 1
        }
    }
}
