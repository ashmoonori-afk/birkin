import Combine
import Foundation

public enum ShellFocusTarget: Equatable, Hashable, Sendable {
    case connection
    case section(ShellSectionID)

    public var evidenceName: String {
        switch self {
        case .connection:
            "connection"
        case .section(let section):
            "section:\(section.rawValue)"
        }
    }

    public var column: ShellColumnID? {
        switch self {
        case .connection:
            nil
        case .section(let section):
            switch section {
            case .sessions, .templates, .workingMemory:
                .navigation
            case .conversation, .composer, .terminal:
                .primary
            case .approvals, .activity, .browserAside, .office, .computerUse:
                .context
            }
        }
    }
}

public enum ShellPresentationError: Error, Equatable, Sendable {
    case timedOut(generation: UInt64)
    case superseded(generation: UInt64, by: UInt64)
}

@MainActor
public final class ShellPresentationModel: ObservableObject {
    @Published public private(set) var target: ShellFocusTarget?
    @Published public private(set) var requestGeneration: UInt64 = 0
    @Published public private(set) var visibleGeneration: UInt64 = 0

    private var waiters:
        [UInt64: [UUID: CheckedContinuation<Void, any Error>]] = [:]
    private var visibleTargets = Set<ShellFocusTarget>()

    public init() {}

    @discardableResult
    public func focus(_ target: ShellFocusTarget) -> UInt64 {
        requestGeneration &+= 1
        self.target = target
        for generation in waiters.keys where generation < requestGeneration {
            let pending = waiters.removeValue(forKey: generation) ?? [:]
            pending.values.forEach {
                $0.resume(throwing: ShellPresentationError.superseded(
                    generation: generation,
                    by: requestGeneration
                ))
            }
        }
        if visibleTargets.contains(target) {
            visibleGeneration = requestGeneration
        }
        return requestGeneration
    }

    public func reportVisibility(
        target: ShellFocusTarget,
        isVisible: Bool
    ) {
        if isVisible {
            visibleTargets.insert(target)
            reportVisible(target: target, generation: requestGeneration)
        } else {
            visibleTargets.remove(target)
        }
    }

    public func reportVisible(
        target: ShellFocusTarget,
        generation: UInt64
    ) {
        guard self.target == target, generation == requestGeneration else { return }
        visibleGeneration = generation
        let continuations: [CheckedContinuation<Void, any Error>]
        if let pending = waiters.removeValue(forKey: generation) {
            continuations = Array(pending.values)
        } else {
            continuations = []
        }
        continuations.forEach { $0.resume(returning: ()) }
    }

    public func waitUntilVisible(
        generation: UInt64,
        timeout: Duration = .seconds(10)
    ) async throws {
        try await waitUntilVisible(
            generation: generation,
            timeout: timeout,
            onWaiting: {}
        )
    }

    func waitUntilVisible(
        generation: UInt64,
        timeout: Duration,
        onWaiting: @escaping @MainActor @Sendable () -> Void
    ) async throws {
        guard visibleGeneration < generation else { return }
        guard generation == requestGeneration else {
            throw ShellPresentationError.superseded(
                generation: generation,
                by: requestGeneration
            )
        }
        try await withThrowingTaskGroup(of: Void.self) { group in
            group.addTask {
                try await self.waitForVisibility(
                    generation: generation,
                    onWaiting: onWaiting
                )
            }
            group.addTask {
                try await Task.sleep(for: timeout)
                throw ShellPresentationError.timedOut(generation: generation)
            }
            defer { group.cancelAll() }
            _ = try await group.next()
        }
    }

    private func waitForVisibility(
        generation: UInt64,
        onWaiting: @escaping @MainActor @Sendable () -> Void
    ) async throws {
        guard visibleGeneration < generation else { return }
        let identifier = UUID()
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                if visibleGeneration >= generation {
                    continuation.resume(returning: ())
                } else if generation != requestGeneration {
                    continuation.resume(
                        throwing: ShellPresentationError.superseded(
                            generation: generation,
                            by: requestGeneration
                        )
                    )
                } else {
                    waiters[generation, default: [:]][identifier] = continuation
                    onWaiting()
                }
            }
        } onCancel: {
            Task { @MainActor in
                self.cancelWaiter(identifier, generation: generation)
            }
        }
    }

    private func cancelWaiter(_ identifier: UUID, generation: UInt64) {
        guard let continuation = waiters[generation]?.removeValue(
            forKey: identifier
        ) else { return }
        continuation.resume(throwing: CancellationError())
        if waiters[generation]?.isEmpty == true {
            waiters.removeValue(forKey: generation)
        }
    }
}
