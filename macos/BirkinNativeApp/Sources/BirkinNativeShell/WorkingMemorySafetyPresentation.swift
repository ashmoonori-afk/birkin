import SwiftUI

public struct WorkingMemoryClearPresentation: Equatable, Sendable {
    public let title: String
    public let explanation: String
    public let confirmAccessibilityLabel: String

    public init(sessionID: String) {
        title = "Clear Working Memory for \(sessionID)?"
        explanation = "This clears corrections, constraints, decisions, incomplete items, evidence, and next actions for this session. It does not clear vault memory, workspace files, or audit history."
        confirmAccessibilityLabel = "Clear session Working Memory only"
    }
}

struct WorkingMemoryClearConfirmationView: View {
    let presentation: WorkingMemoryClearPresentation

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(presentation.title).font(.headline)
            Text(presentation.explanation)
            Button("Clear") {}
                .accessibilityLabel(presentation.confirmAccessibilityLabel)
        }
        .padding(24)
    }
}

public struct WorkingMemoryCanonicalErrorPresentation: Equatable, Sendable {
    public let code: String
    public let message: String
    public let accessibilityLabel: String

    public init(code: String, message: String) {
        self.code = code
        self.message = String(message.prefix(300))
        switch code {
        case "E_WORKING_MEMORY_BUDGET":
            accessibilityLabel = "Working Memory exceeds the canonical 20,000-character render budget. Reduce the update and try again."
        case "E_WORKING_MEMORY_REVISION":
            accessibilityLabel = "Working Memory revision conflict. Review the latest canonical state and try again."
        default:
            accessibilityLabel = "Working Memory update failed. \(String(message.prefix(200)))"
        }
    }
}

struct WorkingMemoryCanonicalErrorView: View {
    let presentation: WorkingMemoryCanonicalErrorPresentation

    var body: some View {
        Label(presentation.message, systemImage: "exclamationmark.triangle")
            .foregroundStyle(.red)
            .accessibilityLabel(presentation.accessibilityLabel)
            .padding(24)
    }
}
