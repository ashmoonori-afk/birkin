import BirkinNativeProtocol
import SwiftUI

public struct WorkingMemoryRow: Equatable, Sendable, Identifiable {
    public let label: String
    public let canonicalFields: [String]
    public let values: [String]
    public var id: String { label }
}

public struct WorkingMemoryPresentation: Equatable, Sendable {
    public let revision: Int
    public let rows: [WorkingMemoryRow]

    public init(projection: NativeWorkingMemoryProjection) {
        revision = projection.revision
        let fields = projection.fields
        rows = [
            WorkingMemoryRow(
                label: "목표",
                canonicalFields: ["GoalState.objective"],
                values: projection.goal.map { [$0.objective] } ?? []
            ),
            WorkingMemoryRow(
                label: "맥락",
                canonicalFields: ["corrections", "decisions", "evidence"],
                values: (fields["corrections"] ?? [])
                    + (fields["decisions"] ?? [])
                    + (fields["evidence"] ?? [])
            ),
            WorkingMemoryRow(
                label: "파일",
                canonicalFields: ["files_evidence"],
                values: projection.filesEvidence.compactMap { item in
                    guard case .string(let summary) = item["summary"] else { return nil }
                    return summary
                }
            ),
            WorkingMemoryRow(
                label: "제약 조건",
                canonicalFields: ["constraints"],
                values: fields["constraints"] ?? []
            ),
            WorkingMemoryRow(
                label: "메모",
                canonicalFields: ["incomplete", "next_actions"],
                values: (fields["incomplete"] ?? []) + (fields["next_actions"] ?? [])
            ),
        ]
    }
}

struct WorkingMemoryView: View {
    let presentation: WorkingMemoryPresentation
    let clearPresentation: WorkingMemoryClearPresentation?
    let canClear: Bool
    let clearAction: () -> Void
    @State private var showsClearConfirmation = false

    init(
        presentation: WorkingMemoryPresentation,
        clearPresentation: WorkingMemoryClearPresentation? = nil,
        canClear: Bool = false,
        clearAction: @escaping () -> Void = {}
    ) {
        self.presentation = presentation
        self.clearPresentation = clearPresentation
        self.canClear = canClear
        self.clearAction = clearAction
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(presentation.rows) { row in
                VStack(alignment: .leading, spacing: 3) {
                    Text(row.label).font(.subheadline.bold())
                    Text(row.values.isEmpty ? "비어 있음" : row.values.joined(separator: "\n"))
                        .foregroundStyle(.secondary)
                    Text(row.canonicalFields.joined(separator: ", "))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel(
                    "\(row.label), \(row.canonicalFields.joined(separator: ", "))"
                )
            }
            Text("버전 \(presentation.revision)")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text("이 기기에만 저장됨")
                .font(.caption)
                .accessibilityLabel("이 기기에만 저장됩니다. Python 서비스가 작업 기억을 관리하며 앱은 별도로 저장하지 않습니다.")
            if let clearPresentation {
                Button("작업 기억 비우기") { showsClearConfirmation = true }
                    .disabled(!canClear)
                    .accessibilityLabel("이 업무에서 비울 작업 기억 범위 확인")
                    .sheet(isPresented: $showsClearConfirmation) {
                        VStack(alignment: .leading, spacing: 16) {
                            Text(clearPresentation.title).font(.headline)
                            Text(clearPresentation.explanation)
                            HStack {
                                Button("취소") { showsClearConfirmation = false }
                                Button("비우기") {
                                    showsClearConfirmation = false
                                    clearAction()
                                }
                                .keyboardShortcut(.defaultAction)
                                .accessibilityLabel(
                                    clearPresentation.confirmAccessibilityLabel
                                )
                            }
                        }
                        .padding(24)
                        .frame(width: 440)
                    }
            }
        }
    }
}
