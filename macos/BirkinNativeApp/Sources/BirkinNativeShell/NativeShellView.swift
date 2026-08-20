import BirkinNativeProtocol
import SwiftUI

public struct NativeShellView: View {
    private let store: NativeProjectionStore
    private let connectionState: NativeConnectionState
    private let now: Date
    private let diagnosticsAction: () -> Void
    private let mutationAction: (ShellMutationControl) -> Void

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var selectedColumn: ShellColumnID

    public init(
        store: NativeProjectionStore,
        connectionState: NativeConnectionState,
        now: Date = Date(),
        initialColumn: ShellColumnID = .navigation,
        diagnosticsAction: @escaping () -> Void = {},
        mutationAction: @escaping (ShellMutationControl) -> Void = { _ in }
    ) {
        self.store = store
        self.connectionState = connectionState
        self.now = now
        self.diagnosticsAction = diagnosticsAction
        self.mutationAction = mutationAction
        _selectedColumn = State(initialValue: initialColumn)
    }

    public var body: some View {
        let structure = ShellStructure(store: store)
        let availability = MutationAvailability(state: connectionState, now: now)
        VStack(spacing: 0) {
            ConnectionStatusPill(
                presentation: ConnectionPresentation(state: connectionState),
                diagnosticsAction: diagnosticsAction
            )
            .padding(12)
            Divider()
            GeometryReader { geometry in
                if dynamicTypeSize.isAccessibilitySize || geometry.size.width < 900 {
                    adaptiveContent(structure, availability: availability)
                } else {
                    threeColumnContent(structure, availability: availability)
                }
            }
        }
        .background(Color(nsColor: .windowBackgroundColor))
    }

    private func threeColumnContent(
        _ structure: ShellStructure,
        availability: MutationAvailability
    ) -> some View {
        HStack(spacing: 0) {
            ForEach(Array(structure.columns.enumerated()), id: \.element.id) { index, column in
                columnView(column, availability: availability)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                if index < structure.columns.count - 1 { Divider() }
            }
        }
    }

    private func adaptiveContent(
        _ structure: ShellStructure,
        availability: MutationAvailability
    ) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Panel")
                    .font(.headline)
                Picker("Panel", selection: $selectedColumn) {
                    ForEach(ShellColumnID.allCases, id: \.self) { column in
                        Text(column.title).tag(column)
                    }
                }
                .pickerStyle(.menu)
            }
            .padding()
            Divider()
            if let column = structure.columns.first(where: { $0.id == selectedColumn }) {
                columnView(column, availability: availability)
            }
        }
    }

    private func columnView(
        _ column: ShellColumn,
        availability: MutationAvailability
    ) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(column.id.title)
                .font(.title2.bold())
                .fixedSize(horizontal: false, vertical: true)
                .padding([.horizontal, .top])
            VStack(alignment: .leading, spacing: 12) {
                ForEach(column.sections, id: \.id) { section in
                    sectionView(section, availability: availability)
                }
            }
            .padding()
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("\(column.id.title) column")
    }

    private func sectionView(
        _ section: ShellSection,
        availability: MutationAvailability
    ) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(section.id.title)
                .font(.headline)
                .fixedSize(horizontal: false, vertical: true)
            stateText(section.state)
            if let control = mutationControl(for: section.id) {
                let surfaceEnabled = isAdvertised(control)
                Button(controlTitle(control)) { mutationAction(control) }
                    .disabled(!availability.isEnabled || !surfaceEnabled)
                if !availability.isEnabled || !surfaceEnabled {
                    Text(availability.disabledReason ?? "Not advertised by Python.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.quaternary.opacity(0.45), in: RoundedRectangle(cornerRadius: 10))
    }

    private func stateText(_ state: ShellSectionState) -> some View {
        Group {
            switch state {
            case .unavailable(let reason): Text(reason)
            case .empty(let message): Text(message)
            case .content(let count): Text("\(count) canonical item\(count == 1 ? "" : "s")")
            }
        }
        .font(.subheadline)
        .foregroundStyle(.secondary)
        .fixedSize(horizontal: false, vertical: true)
    }

    private func mutationControl(for section: ShellSectionID) -> ShellMutationControl? {
        switch section {
        case .sessions: .newSession
        case .composer: .sendMessage
        default: nil
        }
    }

    private func isAdvertised(_ control: ShellMutationControl) -> Bool {
        switch control {
        case .newSession: false
        case .sendMessage: store.projection?.composer.canSend == true
        }
    }

    private func controlTitle(_ control: ShellMutationControl) -> String {
        switch control {
        case .newSession: "New Session"
        case .sendMessage: "Send"
        }
    }
}
