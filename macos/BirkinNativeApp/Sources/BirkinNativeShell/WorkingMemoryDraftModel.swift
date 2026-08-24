import BirkinNativeProtocol
import SwiftUI

public struct WorkingMemoryRenderBudget: Equatable, Sendable {
    public static let canonicalLimit = 20_000
    public let used: Int
    public let limit: Int
    public var remaining: Int { max(0, limit - used) }
    public var isExceeded: Bool { used > limit }
}

public struct WorkingMemoryRevisionConflictPresentation: Equatable, Sendable {
    public let currentRevision: Int
    public let message: String
}

@MainActor
public final class WorkingMemoryDraftModel: ObservableObject {
    public static let editableFields = [
        "corrections", "constraints", "decisions",
        "incomplete", "evidence", "next_actions",
    ]

    @Published public private(set) var baseRevision: Int
    @Published public private(set) var values: [String: [String]]
    @Published public private(set) var conflict: WorkingMemoryRevisionConflictPresentation?
    @Published public private(set) var canonicalError: WorkingMemoryCanonicalErrorPresentation?

    private var baseline: [String: [String]]

    public init(projection: NativeWorkingMemoryProjection) {
        baseRevision = projection.revision
        baseline = Self.editable(projection.fields)
        values = baseline
    }

    public var requestedFields: [String: [String]] {
        Dictionary(uniqueKeysWithValues: Self.editableFields.compactMap { key in
            let value = values[key] ?? []
            return value == baseline[key] ? nil : (key, value)
        })
    }

    public var isDirty: Bool { !requestedFields.isEmpty }

    public var renderBudget: WorkingMemoryRenderBudget {
        let used = Self.editableFields.reduce(0) { count, key in
            count + (values[key] ?? []).reduce(0) { $0 + $1.count }
        }
        return WorkingMemoryRenderBudget(
            used: used, limit: WorkingMemoryRenderBudget.canonicalLimit
        )
    }

    public var canPreview: Bool {
        isDirty && !renderBudget.isExceeded && conflict == nil
    }

    public func setValues(_ newValues: [String], for field: String) {
        guard Self.editableFields.contains(field) else { return }
        values[field] = newValues
        canonicalError = nil
    }

    public func discardChanges() {
        values = baseline
        conflict = nil
        canonicalError = nil
    }

    public func receiveCanonicalFailure(
        code: String,
        message: String,
        currentRevision: Int? = nil
    ) {
        canonicalError = WorkingMemoryCanonicalErrorPresentation(code: code, message: message)
        if code == "E_WORKING_MEMORY_REVISION", let currentRevision {
            conflict = WorkingMemoryRevisionConflictPresentation(
                currentRevision: currentRevision,
                message: message.isEmpty
                    ? "Working Memory changed. Rebase this edit on the latest revision."
                    : String(message.prefix(300))
            )
        }
    }

    public func rebase(on projection: NativeWorkingMemoryProjection) {
        let edits = requestedFields
        baseRevision = projection.revision
        baseline = Self.editable(projection.fields)
        values = baseline
        for (field, editedValues) in edits { values[field] = editedValues }
        conflict = nil
        canonicalError = nil
    }

    public func accept(_ projection: NativeWorkingMemoryProjection) {
        baseRevision = projection.revision
        baseline = Self.editable(projection.fields)
        values = baseline
        conflict = nil
        canonicalError = nil
    }

    private static func editable(_ fields: [String: [String]]) -> [String: [String]] {
        Dictionary(uniqueKeysWithValues: editableFields.map { ($0, fields[$0] ?? []) })
    }
}
