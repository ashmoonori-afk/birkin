import BirkinNativeProtocol
import Foundation

public struct WorkingMemoryPendingUpdate: Equatable, Sendable {
    public let requested: [String: [String]]
    public let effective: NativeWorkingMemoryProjection
}

@MainActor
public final class WorkingMemoryEditorModel: ObservableObject {
    @Published public private(set) var authoritative: NativeWorkingMemoryProjection
    @Published public private(set) var pending: WorkingMemoryPendingUpdate?
    @Published public private(set) var isAwaitingConfirmation = false
    @Published public private(set) var visibleReason: String?
    @Published public private(set) var canonicalError: WorkingMemoryCanonicalErrorPresentation?
    @Published public private(set) var revisionConflict: WorkingMemoryRevisionConflictPresentation?

    public init(authoritative: NativeWorkingMemoryProjection) {
        self.authoritative = authoritative
    }

    public var isOptimistic: Bool { pending != nil }

    public func receivePreview(
        requested: [String: [String]],
        effective: NativeWorkingMemoryProjection
    ) {
        pending = WorkingMemoryPendingUpdate(requested: requested, effective: effective)
        isAwaitingConfirmation = false
        visibleReason = nil
        canonicalError = nil
        revisionConflict = nil
    }

    @discardableResult
    public func submit(
        availability: MutationAvailability,
        expectedCursor: Int,
        session: NativeReadySession,
        submit: (NativeCommandRequest) -> Void
    ) -> Bool {
        guard availability.isEnabled else {
            visibleReason = availability.disabledReason
            return false
        }
        guard session.supportedCommands.contains("memory.write") else {
            visibleReason = "Working Memory mutation is not advertised by Python."
            return false
        }
        guard let pending else {
            visibleReason = "Preview a Working Memory update before submitting."
            return false
        }
        var fieldValues = NativeJSONObject()
        for key in pending.requested.keys.sorted() {
            try? fieldValues.append(
                key: key,
                value: .array(
                    (pending.requested[key] ?? []).map(NativeJSONValue.string)
                )
            )
        }
        let commandID = "memory-\(UUID().uuidString.lowercased())"
        submit(NativeCommandRequest(
            frameID: "frame-\(commandID)",
            commandID: commandID,
            expectedCursor: expectedCursor,
            commandType: "memory.write",
            payload: [
                "op": .string("merge"),
                "expected_revision": .int(authoritative.revision),
                "fields": .object(fieldValues),
            ],
            sessionCapability: session.sessionCapability,
            viewID: "working-memory"
        ))
        isAwaitingConfirmation = true
        visibleReason = nil
        return true
    }

    @discardableResult
    public func submitClear(
        availability: MutationAvailability,
        expectedCursor: Int,
        session: NativeReadySession,
        submit: (NativeCommandRequest) -> Void
    ) -> Bool {
        guard availability.isEnabled else {
            visibleReason = availability.disabledReason
            return false
        }
        guard session.supportedCommands.contains("memory.write") else {
            visibleReason = "Working Memory mutation is not advertised by Python."
            return false
        }
        let commandID = "memory-clear-\(UUID().uuidString.lowercased())"
        submit(NativeCommandRequest(
            frameID: "frame-\(commandID)",
            commandID: commandID,
            expectedCursor: expectedCursor,
            commandType: "memory.write",
            payload: [
                "op": .string("clear"),
                "expected_revision": .int(authoritative.revision),
            ],
            sessionCapability: session.sessionCapability,
            viewID: "working-memory"
        ))
        isAwaitingConfirmation = true
        visibleReason = nil
        return true
    }

    public func confirm(_ projection: NativeWorkingMemoryProjection) {
        guard projection.revision > authoritative.revision else { return }
        authoritative = projection
        if pending?.effective.revision == projection.revision {
            pending = nil
            isAwaitingConfirmation = false
        }
    }

    public func renderCanonicalError(
        code: String, message: String, currentRevision: Int? = nil
    ) {
        let bounded = String(message.prefix(300))
        canonicalError = WorkingMemoryCanonicalErrorPresentation(
            code: code, message: bounded
        )
        switch code {
        case "E_WORKING_MEMORY_REVISION":
            visibleReason = bounded.isEmpty
                ? "Working Memory changed. Review the latest revision and try again."
                : bounded
            if let currentRevision {
                revisionConflict = WorkingMemoryRevisionConflictPresentation(
                    currentRevision: currentRevision,
                    message: visibleReason ?? "Working Memory revision conflict."
                )
            }
        case "E_WORKING_MEMORY_BUDGET":
            visibleReason = bounded.isEmpty
                ? "Working Memory exceeds the 20,000-character render budget."
                : bounded
        default:
            visibleReason = bounded
        }
        isAwaitingConfirmation = false
    }
}
