import AppKit
import BirkinNativeProtocol
import SwiftUI

private enum ApprovalTrustPalette {
    static func safe(_ scheme: ColorScheme) -> Color {
        scheme == .light
            ? Color(red: 0.00, green: 0.42, blue: 0.21)
            : Color(red: 0.37, green: 0.90, blue: 0.55)
    }

    static func caution(_ scheme: ColorScheme) -> Color {
        scheme == .light
            ? Color(red: 0.48, green: 0.26, blue: 0.00)
            : Color(red: 1.00, green: 0.76, blue: 0.40)
    }

    static func danger(_ scheme: ColorScheme) -> Color {
        scheme == .light
            ? Color(red: 0.62, green: 0.08, blue: 0.11)
            : Color(red: 1.00, green: 0.48, blue: 0.50)
    }

    static func assurance(_ scheme: ColorScheme) -> Color {
        scheme == .light
            ? Color(red: 0.09, green: 0.35, blue: 0.65)
            : Color(red: 0.46, green: 0.72, blue: 1.00)
    }

    static func critical(_ scheme: ColorScheme) -> Color {
        scheme == .light
            ? Color(red: 0.39, green: 0.21, blue: 0.65)
            : Color(red: 0.78, green: 0.60, blue: 1.00)
    }
}

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
    public let status: String
    public let receiptReference: String?
    public let sourceFilename: String?
    public let destination: String?
    public let overwriteApproved: Bool?
    public let authorityDigest: String?
    public let requester: String?
    public let rejectionResult: String?
    public let expiresAt: String?
    public let availableDecisions: [ApprovalDecision]

    public var destinationDisplay: String? {
        destination.map { Self.abbreviate($0, limit: 48) }
    }

    public var authorityDigestDisplay: String? {
        authorityDigest.map { Self.abbreviate($0, limit: 27) }
    }

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
        status = item.text("status") ?? "pending"
        receiptReference = item.text("receipt_ref")
        sourceFilename = item.text("source_filename")
        destination = item.text("destination")
        overwriteApproved = item.flag("overwrite_approved")
        authorityDigest = item.text("authority_digest")
        requester = item.text("requester")
        rejectionResult = item.text("rejection_result")
        expiresAt = item.text("expires_at")
        isDecided = item.flag("decided") ?? Self.resolvedStatuses.contains(status)
        availableDecisions = isDecided ? [] : [.reject, .approve]
    }

    private static let resolvedStatuses = Set([
        "approved", "rejected", "answered_elsewhere", "expired", "failed",
    ])

    private static func abbreviate(_ value: String, limit: Int) -> String {
        guard value.count > limit else { return value }
        let leftCount = (limit - 3) / 2
        let rightCount = limit - leftCount - 3
        return "\(value.prefix(leftCount))...\(value.suffix(rightCount))"
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
    public let approve: () -> Bool
    public let reject: () -> Bool
    @State private var pendingDecision: ApprovalDecision?
    @State private var isSubmitting = false
    @State private var submissionError: String?
    @Environment(\.colorScheme) private var colorScheme

    public init(
        presentation: ApprovalCardPresentation,
        canDecide: Bool,
        approve: @escaping () -> Bool,
        reject: @escaping () -> Bool
    ) {
        self.presentation = presentation
        self.canDecide = canDecide
        self.approve = approve
        self.reject = reject
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ViewThatFits(in: .horizontal) {
                HStack {
                    riskBadge
                    sealedBadge
                    Spacer(minLength: 0)
                }
                VStack(alignment: .leading, spacing: 5) {
                    riskBadge
                    sealedBadge
                }
            }
            Text(presentation.category.replacingOccurrences(of: "_", with: " "))
                .font(.caption).foregroundStyle(.secondary)
            Text(presentation.summary).font(.headline)
            if !presentation.description.isEmpty {
                Text(presentation.description).font(.subheadline).foregroundStyle(.secondary)
            }
            VStack(alignment: .leading, spacing: 3) {
                Text("REQUESTED BY: \(presentation.requester ?? "Unavailable")")
                    .font(.caption.weight(.semibold))
                Text("EXPIRES: \(presentation.expiresAt ?? "Not specified")")
                    .font(.caption).foregroundStyle(.secondary)
                Text(
                    presentation.rejectionResult
                        ?? "Rejection outcome unavailable"
                )
                .font(.caption)
            }
            .accessibilityElement(children: .combine)
            if presentation.sourceFilename != nil
                || presentation.destination != nil
                || presentation.authorityDigest != nil
            {
                VStack(alignment: .leading, spacing: 7) {
                    if let source = presentation.sourceFilename {
                        trustDetail("SOURCE", value: source)
                    }
                    if let destination = presentation.destination,
                       let display = presentation.destinationDisplay {
                        trustDetail(
                            "DESTINATION",
                            value: display,
                            fullValue: destination,
                            monospaced: true
                        )
                        Label(overwriteLabel, systemImage: overwriteSymbol)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(overwriteColor)
                    }
                    if let digest = presentation.authorityDigest,
                       let display = presentation.authorityDigestDisplay {
                        trustDetail(
                            "APPROVAL AUTHORITY",
                            value: display,
                            fullValue: digest,
                            monospaced: true
                        )
                    }
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(.secondary.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
                .overlay {
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(.secondary.opacity(0.25), lineWidth: 1)
                }
            }
            if presentation.availableDecisions.isEmpty {
                Label(outcomeLabel, systemImage: outcomeSymbol)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.secondary)
                if let receipt = presentation.receiptReference {
                    Text(receipt)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
            } else if isSubmitting {
                VStack(alignment: .leading, spacing: 7) {
                    ProgressView("Sending approval decision...")
                        .font(.subheadline)
                        .accessibilityLabel("Sending approval decision")
                    Text("Awaiting canonical confirmation.")
                        .font(.caption).foregroundStyle(.secondary)
                    Button("Return to approval card") {
                        isSubmitting = false
                        submissionError = "Decision status is unknown. Review connection and retry."
                    }
                }
            } else if let pendingDecision {
                VStack(alignment: .leading, spacing: 8) {
                    Text(
                        pendingDecision == .approve
                            ? "Confirm this reviewed write?"
                            : "Confirm rejection?"
                    )
                    .font(.subheadline.weight(.semibold))
                    if let destination = presentation.destinationDisplay {
                        Text(destination).font(.caption.monospaced())
                    }
                    Text(overwriteLabel)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(overwriteColor)
                    HStack {
                        Button("Cancel") {
                            self.pendingDecision = nil
                        }
                        if pendingDecision == .approve {
                            Button("Confirm Approve") {
                                submitConfirmed(.approve)
                            }
                            .buttonStyle(.borderedProminent)
                        } else {
                            Button("Confirm Reject") {
                                submitConfirmed(.reject)
                            }
                            .buttonStyle(.bordered)
                        }
                    }
                }
                .disabled(!canDecide)
            } else {
                if let submissionError {
                    Label(submissionError, systemImage: "exclamationmark.triangle.fill")
                        .font(.caption)
                        .foregroundStyle(ApprovalTrustPalette.danger(colorScheme))
                }
                HStack {
                    Button("Reject", role: .destructive) {
                        pendingDecision = .reject
                    }
                        .accessibilityLabel("Reject approval")
                    Button("Approve") {
                        pendingDecision = .approve
                    }
                        .buttonStyle(.bordered)
                        .accessibilityLabel("Approve request")
                }
                .disabled(!canDecide)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 12))
        .accessibilityElement(children: .contain)
        .accessibilityLabel(accessibilitySummary)
    }

    private var riskBadge: some View {
        Text("\(presentation.risk.rawValue.uppercased()) RISK")
            .font(.caption.bold()).padding(.horizontal, 8).padding(.vertical, 4)
            .background(riskColor.opacity(0.12), in: Capsule())
            .foregroundStyle(riskColor)
    }

    private var sealedBadge: some View {
        Label(
            presentation.isSealed ? "SEALED" : "NOT SEALED",
            systemImage: presentation.isSealed ? "lock.shield" : "lock.open"
        )
        .font(.caption.weight(.semibold))
        .foregroundStyle(
            presentation.isSealed
                ? ApprovalTrustPalette.assurance(colorScheme)
                : ApprovalTrustPalette.danger(colorScheme)
        )
    }

    private func submitConfirmed(_ decision: ApprovalDecision) {
        submissionError = nil
        let submitted = decision == .approve ? approve() : reject()
        pendingDecision = nil
        isSubmitting = submitted
        if !submitted {
            submissionError = "Decision was not sent. Review connection and retry."
        }
    }

    @ViewBuilder
    private func trustDetail(
        _ label: String,
        value: String,
        fullValue: String? = nil,
        monospaced: Bool = false
    ) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption.weight(.semibold)).foregroundStyle(.primary)
            if monospaced {
                Text(value).font(.caption.monospaced()).foregroundStyle(.primary)
                    .lineLimit(2).truncationMode(.middle).textSelection(.enabled)
                    .help(fullValue ?? value)
                    .accessibilityValue(fullValue ?? value)
                    .contextMenu {
                        Button("Copy full value") {
                            copy(fullValue ?? value)
                        }
                    }
            } else {
                Text(value).font(.caption).foregroundStyle(.primary)
                    .lineLimit(2).truncationMode(.middle).textSelection(.enabled)
                    .help(fullValue ?? value)
                    .accessibilityValue(fullValue ?? value)
                    .contextMenu {
                        Button("Copy full value") {
                            copy(fullValue ?? value)
                        }
                    }
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var accessibilitySummary: String {
        let destination = presentation.destination ?? "destination unavailable"
        return [
            "\(presentation.risk.rawValue) risk approval",
            presentation.summary,
            presentation.isSealed ? "sealed" : "not sealed",
            "requested by \(presentation.requester ?? "unavailable")",
            "destination \(destination)",
            overwriteLabel,
            presentation.rejectionResult ?? "rejection outcome unavailable",
        ].joined(separator: ", ")
    }

    private var overwriteLabel: String {
        switch presentation.overwriteApproved {
        case true: "WARNING: Existing file may be replaced"
        case false: "SAFE: Existing file must not already exist"
        case nil: "UNKNOWN: Overwrite authority unavailable"
        }
    }

    private var overwriteSymbol: String {
        switch presentation.overwriteApproved {
        case true: "exclamationmark.triangle.fill"
        case false: "checkmark.shield.fill"
        case nil: "questionmark.diamond.fill"
        }
    }

    private var overwriteColor: Color {
        switch presentation.overwriteApproved {
        case true: ApprovalTrustPalette.danger(colorScheme)
        case false: ApprovalTrustPalette.safe(colorScheme)
        case nil: ApprovalTrustPalette.caution(colorScheme)
        }
    }

    private func copy(_ value: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(value, forType: .string)
    }

    private var riskColor: Color {
        switch presentation.risk {
        case .low: ApprovalTrustPalette.safe(colorScheme)
        case .medium: ApprovalTrustPalette.caution(colorScheme)
        case .high: ApprovalTrustPalette.danger(colorScheme)
        case .critical: ApprovalTrustPalette.critical(colorScheme)
        }
    }

    private var outcomeLabel: String {
        switch presentation.status {
        case "approved": "Approved"
        case "rejected": "Rejected"
        case "answered_elsewhere": "Answered elsewhere"
        case "expired": "Expired"
        case "failed": "Failed"
        default: presentation.status.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }

    private var outcomeSymbol: String {
        switch presentation.status {
        case "approved": "checkmark.circle.fill"
        case "answered_elsewhere": "person.crop.circle.badge.checkmark"
        case "expired": "clock.badge.exclamationmark"
        case "failed": "xmark.octagon.fill"
        default: "hand.raised.fill"
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
