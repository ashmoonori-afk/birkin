import BirkinNativeProtocol
import SwiftUI

@MainActor
public final class ActivityFilterModel: ObservableObject {
    @Published public var hideRead = false
    @Published public private(set) var readIDs: Set<String> = []

    public init() {}

    public func markRead(_ id: String) {
        readIDs.insert(id)
    }

    public func visible(_ items: [NativeJSONObject]) -> [NativeJSONObject] {
        guard hideRead else { return items }
        return items.filter { item in
            guard case .string(let id) = item["id"] else { return true }
            return !readIDs.contains(id)
        }
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
            Toggle("Hide read", isOn: $filter.hideRead)
                .accessibilityLabel("Hide read activity")
                .accessibilityHint("Filters this view only and is not saved")
            ForEach(Array(filter.visible(items).enumerated()), id: \.offset) { _, item in
                Button {
                    if case .string(let id) = item["id"] { filter.markRead(id) }
                } label: {
                    HStack {
                        if case .string(let kind) = item["kind"], kind == "integrity_warning" {
                            Image(systemName: "exclamationmark.shield")
                        } else {
                            Image(systemName: "checkmark.seal")
                        }
                        if case .string(let summary) = item["summary"] {
                            Text(summary)
                        }
                    }
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Activity receipt")
            }
        }
    }
}
