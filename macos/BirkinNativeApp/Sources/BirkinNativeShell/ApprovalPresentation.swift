import BirkinNativeProtocol
import SwiftUI

public enum ApprovalRisk: String, Equatable, Sendable {
    case low, medium, high, critical
}

public enum ApprovalDecision: String, Equatable, Sendable {
    case approve, reject
}

public struct ApprovalCardPresentation: Equatable, Sendable, Identifiable {
    public let id: String
    public let summary: String
    public let description: String
    public let category: String
    public let risk: ApprovalRisk
    public let isSealed: Bool
    public let isDecided: Bool

    public init?(item: NativeJSONObject) {
        guard item.text("kind") == "approval",
              let id = item.text("id"), !id.isEmpty,
              let riskText = item.text("risk"),
              let risk = ApprovalRisk(rawValue: riskText) else { return nil }
        self.id = id
        summary = item.text("summary") ?? "Approval"
        description = item.text("description") ?? ""
        category = item.text("category") ?? "unknown"
        self.risk = risk
        isSealed = item.flag("sealed") ?? false
        isDecided = item.flag("decided") ?? false
    }

    @discardableResult
    public func submit(
        _ decision: ApprovalDecision,
        availability: MutationAvailability,
        commandAdvertised: Bool,
        expectedCursor: Int,
        sessionCapability: String,
        submit: (NativeCommandRequest) -> Void
    ) -> Bool {
        guard availability.isEnabled, commandAdvertised, !isDecided else { return false }
        let commandID = "approval-\(decision.rawValue)-\(UUID().uuidString.lowercased())"
        submit(NativeCommandRequest(
            frameID: "frame-\(commandID)", commandID: commandID,
            expectedCursor: expectedCursor, commandType: "approval.answer",
            payload: [
                "approval_id": .string(id),
                "decision": .string(decision.rawValue),
            ],
            sessionCapability: sessionCapability, viewID: "approvals"
        ))
        return true
    }
}

public struct ApprovalCardView: View {
    public let presentation: ApprovalCardPresentation
    public let canDecide: Bool
    public let approve: () -> Void
    public let reject: () -> Void

    public init(
        presentation: ApprovalCardPresentation,
        canDecide: Bool,
        approve: @escaping () -> Void,
        reject: @escaping () -> Void
    ) {
        self.presentation = presentation
        self.canDecide = canDecide
        self.approve = approve
        self.reject = reject
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(presentation.risk.rawValue.uppercased())
                    .font(.caption.bold()).padding(.horizontal, 8).padding(.vertical, 4)
                    .background(riskColor.opacity(0.18), in: Capsule())
                    .foregroundStyle(riskColor)
                Text(presentation.category).font(.caption).foregroundStyle(.secondary)
                if presentation.isSealed {
                    Label("Sealed", systemImage: "lock.shield").font(.caption)
                }
            }
            Text(presentation.summary).font(.headline)
            if !presentation.description.isEmpty {
                Text(presentation.description).font(.subheadline).foregroundStyle(.secondary)
            }
            HStack {
                Button("Reject", role: .destructive, action: reject)
                    .accessibilityLabel("Reject approval")
                Button("Approve", action: approve)
                    .buttonStyle(.borderedProminent)
                    .accessibilityLabel("Approve request")
            }.disabled(!canDecide || presentation.isDecided)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 12))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("\(presentation.risk.rawValue) risk approval: \(presentation.summary)")
    }

    private var riskColor: Color {
        switch presentation.risk {
        case .low: .green
        case .medium: .orange
        case .high: .red
        case .critical: .purple
        }
    }
}

private extension NativeJSONObject {
    func text(_ key: String) -> String? {
        guard case .string(let value) = self[key] else { return nil }
        return value
    }

    func flag(_ key: String) -> Bool? {
        guard case .bool(let value) = self[key] else { return nil }
        return value
    }
}
