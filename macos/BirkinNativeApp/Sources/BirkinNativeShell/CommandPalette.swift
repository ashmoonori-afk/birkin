import SwiftUI

public struct CommandPaletteItem: Equatable, Identifiable, Sendable {
    public let commandType: String
    public let title: String

    public var id: String { commandType }
}

public struct CommandPaletteModel: Equatable, Sendable {
    public let items: [CommandPaletteItem]

    public init(advertisedCommands: Set<String>) {
        items = advertisedCommands.sorted().map { commandType in
            CommandPaletteItem(
                commandType: commandType,
                title: commandType
                    .split(separator: ".")
                    .map { $0.replacingOccurrences(of: "_", with: " ").capitalized }
                    .joined(separator: " ")
            )
        }
    }

    public func filtered(by query: String) -> [CommandPaletteItem] {
        let needle = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !needle.isEmpty else { return items }
        return items.filter { item in
            Self.containsSubsequence(needle, in: item.commandType)
                || Self.containsSubsequence(needle, in: item.title)
        }
    }

    private static func containsSubsequence(
        _ query: String,
        in candidate: String
    ) -> Bool {
        var candidateCharacters = candidate.lowercased().makeIterator()
        for expected in query.lowercased() {
            var matched = false
            while let current = candidateCharacters.next() {
                if current == expected {
                    matched = true
                    break
                }
            }
            if !matched { return false }
        }
        return true
    }
}

public struct CommandPaletteView: View {
    private let model: CommandPaletteModel
    private let select: (CommandPaletteItem) -> Void

    @Environment(\.dismiss) private var dismiss
    @FocusState private var searchFocused: Bool
    @State private var query = ""

    public init(
        model: CommandPaletteModel,
        select: @escaping (CommandPaletteItem) -> Void
    ) {
        self.model = model
        self.select = select
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            TextField("Search advertised commands", text: $query)
                .textFieldStyle(.plain)
                .padding(14)
                .focused($searchFocused)
                .accessibilityLabel("Command palette search")
            Divider()
            if model.items.isEmpty {
                VStack(spacing: 8) {
                    Label("No Commands Available", systemImage: "command")
                        .font(.headline)
                    Text("Python advertised no command handlers.")
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List(model.filtered(by: query)) { item in
                    Button {
                        select(item)
                        dismiss()
                    } label: {
                        HStack {
                            Text(item.title)
                            Spacer()
                            Text(item.commandType)
                                .font(.caption.monospaced())
                                .foregroundStyle(.secondary)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(item.title)
                    .accessibilityValue(item.commandType)
                }
                .accessibilityLabel("Advertised commands")
            }
        }
        .frame(minWidth: 480, idealWidth: 560, minHeight: 360, idealHeight: 440)
        .onAppear { searchFocused = true }
        .onExitCommand { dismiss() }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Command palette")
    }
}
