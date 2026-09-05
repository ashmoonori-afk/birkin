import BirkinNativeProtocol
import SwiftUI

public enum ActivityKind: Equatable, Sendable {
    case tool
    case receipt
    case failure
    case integrityWarning
    case other
}

public enum ActivityState: Equatable, Sendable {
    case running
    case succeeded
    case failed
    case actionNeeded
    case pending
}

public struct ActivityDetail: Equatable, Sendable, Identifiable {
    public let label: String
    public let value: String
    public var id: String { label }
}

public struct ActivityPresentation: Equatable, Sendable, Identifiable {
    public let id: String
    public let kind: ActivityKind
    public let state: ActivityState
    public let summary: String
    public let details: [ActivityDetail]
    public let receiptReference: String?
    public let failure: CanonicalFailurePresentation?

    public var isExpandable: Bool { !details.isEmpty || failure != nil }

    public init?(_ raw: NativeJSONObject) {
        guard let id = raw.string("id"), let rawKind = raw.string("kind") else { return nil }
        let uiState = raw.string("ui_state") ?? "pending"
        self.id = id
        summary = raw.string("summary") ?? rawKind
        state = switch uiState {
        case "running": .running
        case "succeeded", "completed": .succeeded
        case "failed": .failed
        case "action_needed": .actionNeeded
        default: .pending
        }
        if rawKind == "receipt" {
            kind = .receipt
        } else if rawKind == "integrity_warning" {
            kind = .integrityWarning
        } else if rawKind == "failure" || uiState == "failed" {
            kind = .failure
        } else if rawKind == "activity" || raw.string("status") == "started" {
            kind = .tool
        } else {
            kind = .other
        }
        receiptReference = raw.string("receipt_ref")
        failure = kind == .failure ? CanonicalFailurePresentation(
            code: raw.string("code") ?? raw.string("refusal_code"),
            message: String((raw.string("message") ?? summary).prefix(300)),
            retryable: raw.bool("retryable") ?? false
        ) : nil
        details = Self.detailFields.compactMap { key, label in
            raw.string(key).map { ActivityDetail(label: label, value: $0) }
        }
    }

    private static let detailFields: [(String, String)] = [
        ("target", "대상"), ("status", "상태"),
        ("effect", "영향"), ("receipt_ref", "처리 기록"),
        ("snapshot_ref", "상태 기록"), ("refusal_code", "거부 사유"),
    ]
}

@MainActor
public final class ActivityFilterModel: ObservableObject {
    @Published public var hideRead = false
    @Published public private(set) var readIDs: Set<String> = []
    @Published public private(set) var expandedIDs: Set<String> = []

    public init() {}

    public func markRead(_ id: String) { readIDs.insert(id) }

    public func toggleExpanded(_ id: String) {
        if !expandedIDs.insert(id).inserted { expandedIDs.remove(id) }
    }

    public func visible(_ items: [NativeJSONObject]) -> [NativeJSONObject] {
        guard hideRead else { return items }
        return items.filter { item in
            guard let id = item.string("id") else { return true }
            return !readIDs.contains(id)
        }
    }

    public func presentations(_ items: [NativeJSONObject]) -> [ActivityPresentation] {
        visible(items).compactMap(ActivityPresentation.init)
    }
}

public struct ActivityListView: View {
    public let items: [NativeJSONObject]
    @ObservedObject public var filter: ActivityFilterModel

    public init(items: [NativeJSONObject], filter: ActivityFilterModel) {
        self.items = items
        self.filter = filter
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Toggle("확인한 항목 숨기기", isOn: $filter.hideRead)
                .accessibilityLabel("확인한 진행 기록 숨기기")
                .accessibilityHint("현재 화면에만 적용되며 저장되지 않습니다")
            ForEach(filter.presentations(items)) { item in
                VStack(alignment: .leading, spacing: 4) {
                    Button {
                        filter.markRead(item.id)
                        if item.isExpandable { filter.toggleExpanded(item.id) }
                    } label: {
                        Label(item.summary, systemImage: icon(item.kind))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(accessibilityLabel(item.kind))
                    if filter.expandedIDs.contains(item.id) {
                        ForEach(item.details) { detail in
                            Text("\(detail.label): \(detail.value)")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        if let failure = item.failure {
                            Text(failure.message).font(.caption).foregroundStyle(.red)
                        }
                    }
                }
            }
        }
    }

    private func icon(_ kind: ActivityKind) -> String {
        switch kind {
        case .tool: "hammer"
        case .receipt: "checkmark.seal"
        case .failure: "xmark.octagon"
        case .integrityWarning: "exclamationmark.shield"
        case .other: "circle"
        }
    }

    private func accessibilityLabel(_ kind: ActivityKind) -> String {
        switch kind {
        case .tool: "도구 작업"
        case .receipt: "작업 처리 기록"
        case .failure: "실패한 작업"
        case .integrityWarning: "무결성 경고"
        case .other: "진행 기록"
        }
    }
}

private extension NativeJSONObject {
    func string(_ key: String) -> String? {
        guard case .string(let value) = self[key] else { return nil }
        return value
    }

    func bool(_ key: String) -> Bool? {
        guard case .bool(let value) = self[key] else { return nil }
        return value
    }
}
