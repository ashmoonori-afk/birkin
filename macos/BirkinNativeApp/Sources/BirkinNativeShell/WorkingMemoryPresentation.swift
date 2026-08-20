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
                label: "Goals",
                canonicalFields: ["GoalState.objective"],
                values: projection.goal.map { [$0.objective] } ?? []
            ),
            WorkingMemoryRow(
                label: "Context",
                canonicalFields: ["corrections", "decisions", "evidence"],
                values: (fields["corrections"] ?? [])
                    + (fields["decisions"] ?? [])
                    + (fields["evidence"] ?? [])
            ),
            WorkingMemoryRow(
                label: "Files",
                canonicalFields: ["files_evidence"],
                values: projection.filesEvidence.compactMap { item in
                    guard case .string(let summary) = item["summary"] else { return nil }
                    return summary
                }
            ),
            WorkingMemoryRow(
                label: "Constraints",
                canonicalFields: ["constraints"],
                values: fields["constraints"] ?? []
            ),
            WorkingMemoryRow(
                label: "Notes",
                canonicalFields: ["incomplete", "next_actions"],
                values: (fields["incomplete"] ?? []) + (fields["next_actions"] ?? [])
            ),
        ]
    }
}

struct WorkingMemoryView: View {
    let presentation: WorkingMemoryPresentation

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(presentation.rows) { row in
                VStack(alignment: .leading, spacing: 3) {
                    Text(row.label).font(.subheadline.bold())
                    Text(row.values.isEmpty ? "None" : row.values.joined(separator: "\n"))
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
            Text("Revision \(presentation.revision)")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text("Stored locally on this device")
                .font(.caption)
                .accessibilityLabel("Stored locally on this device. Python owns storage; the native app does not persist Working Memory.")
        }
    }
}
