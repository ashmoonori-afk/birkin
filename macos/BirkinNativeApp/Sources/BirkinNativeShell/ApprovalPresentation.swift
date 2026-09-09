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
        summary = item.text("summary") ?? "승인 요청"
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
                Text("요청자: \(presentation.requester ?? "확인할 수 없음")")
                    .font(.caption.weight(.semibold))
                Text("만료: \(presentation.expiresAt ?? "지정되지 않음")")
                    .font(.caption).foregroundStyle(.secondary)
                Text(
                    presentation.rejectionResult
                        ?? "거부할 때의 결과를 확인할 수 없습니다"
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
                        trustDetail("원본", value: source)
                    }
                    if let destination = presentation.destination,
                       let display = presentation.destinationDisplay {
                        trustDetail(
                            "저장 위치",
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
                            "승인 권한",
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
                    ProgressView("승인 결정을 보내는 중입니다...")
                        .font(.subheadline)
                        .accessibilityLabel("승인 결정을 보내는 중")
                    Text("최종 확인을 기다리고 있습니다.")
                        .font(.caption).foregroundStyle(.secondary)
                    Button("승인 카드로 돌아가기") {
                        isSubmitting = false
                        submissionError = "승인 상태를 확인할 수 없습니다. 연결을 확인하고 다시 시도하세요."
                    }
                }
            } else if let pendingDecision {
                VStack(alignment: .leading, spacing: 8) {
                    Text(
                        pendingDecision == .approve
                            ? "검토한 내용대로 실행할까요?"
                            : "요청을 거부할까요?"
                    )
                    .font(.subheadline.weight(.semibold))
                    if let destination = presentation.destinationDisplay {
                        Text(destination).font(.caption.monospaced())
                    }
                    Text(overwriteLabel)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(overwriteColor)
                    HStack {
                        Button("취소") {
                            self.pendingDecision = nil
                        }
                        if pendingDecision == .approve {
                            Button("승인 확정") {
                                submitConfirmed(.approve)
                            }
                            .buttonStyle(.borderedProminent)
                        } else {
                            Button("거부 확정") {
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
                    Button("거부", role: .destructive) {
                        pendingDecision = .reject
                    }
                        .accessibilityLabel("요청한 작업 거부")
                    Button("승인") {
                        pendingDecision = .approve
                    }
                        .buttonStyle(.bordered)
                        .accessibilityLabel("요청한 작업 승인")
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
        Text("위험도: \(riskLabel)")
            .font(.caption.bold()).padding(.horizontal, 8).padding(.vertical, 4)
            .background(riskColor.opacity(0.12), in: Capsule())
            .foregroundStyle(riskColor)
    }

    private var sealedBadge: some View {
        Label(
            presentation.isSealed ? "검토 내용 고정됨" : "검토 내용 고정 안 됨",
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
            submissionError = "승인 결정을 보내지 못했습니다. 연결을 확인하고 다시 시도하세요."
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
                        Button("전체 값 복사") {
                            copy(fullValue ?? value)
                        }
                    }
            } else {
                Text(value).font(.caption).foregroundStyle(.primary)
                    .lineLimit(2).truncationMode(.middle).textSelection(.enabled)
                    .help(fullValue ?? value)
                    .accessibilityValue(fullValue ?? value)
                    .contextMenu {
                        Button("전체 값 복사") {
                            copy(fullValue ?? value)
                        }
                    }
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var accessibilitySummary: String {
        let destination = presentation.destination ?? "저장 위치를 확인할 수 없음"
        return [
            "위험도 \(riskLabel) 승인 요청",
            presentation.summary,
            presentation.isSealed ? "검토 내용 고정됨" : "검토 내용 고정 안 됨",
            "요청자 \(presentation.requester ?? "확인할 수 없음")",
            "저장 위치 \(destination)",
            overwriteLabel,
            presentation.rejectionResult ?? "거부할 때의 결과를 확인할 수 없음",
        ].joined(separator: ", ")
    }

    private var overwriteLabel: String {
        switch presentation.overwriteApproved {
        case true: "주의: 기존 파일을 덮어쓸 수 있습니다"
        case false: "안전: 기존 파일이 없어야 합니다"
        case nil: "덮어쓰기 권한을 확인할 수 없습니다"
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
        case "approved": "승인됨"
        case "rejected": "거부됨"
        case "answered_elsewhere": "다른 위치에서 결정됨"
        case "expired": "만료됨"
        case "failed": "실패함"
        default: "결정 상태를 확인할 수 없음"
        }
    }

    private var riskLabel: String {
        switch presentation.risk {
        case .low: "낮음"
        case .medium: "보통"
        case .high: "높음"
        case .critical: "매우 높음"
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
