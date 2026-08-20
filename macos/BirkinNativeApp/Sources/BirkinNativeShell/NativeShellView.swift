import BirkinNativeProtocol
import SwiftUI

public struct NativeShellView: View {
    private let store: NativeProjectionStore
    private let connectionState: NativeConnectionState
    private let now: Date
    private let diagnosticsAction: () -> Void
    private let mutationAction: (ShellMutationControl) -> Void
    private let templateCommandAction: (NativeCommandRequest) -> Void

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var selectedColumn: ShellColumnID
    @StateObject private var templateLauncher: TemplateLauncherModel
    @StateObject private var conversationComposer: ConversationComposerModel

    public init(
        store: NativeProjectionStore,
        connectionState: NativeConnectionState,
        now: Date = Date(),
        initialColumn: ShellColumnID = .navigation,
        diagnosticsAction: @escaping () -> Void = {},
        mutationAction: @escaping (ShellMutationControl) -> Void = { _ in },
        templateCommandAction: @escaping (NativeCommandRequest) -> Void = { _ in },
        makeSessionID: @escaping () -> String = { UUID().uuidString.lowercased() }
    ) {
        self.store = store
        self.connectionState = connectionState
        self.now = now
        self.diagnosticsAction = diagnosticsAction
        self.mutationAction = mutationAction
        self.templateCommandAction = templateCommandAction
        _selectedColumn = State(initialValue: initialColumn)
        _templateLauncher = StateObject(wrappedValue: TemplateLauncherModel(
            presets: Self.readySession(in: connectionState)?.sessionPresets ?? [],
            makeSessionID: makeSessionID
        ))
        _conversationComposer = StateObject(wrappedValue: ConversationComposerModel())
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
                let layout = ShellLayoutPlan(
                    windowWidth: geometry.size.width,
                    dynamicTypeSize: dynamicTypeSize
                )
                if layout.mode == .panelNavigation {
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
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .center, spacing: 12) { panelSelector }
                VStack(alignment: .leading, spacing: 8) { panelSelector }
            }
            .padding()
            Divider()
            if let column = structure.columns.first(where: { $0.id == selectedColumn }) {
                columnView(column, availability: availability)
            }
        }
    }

    @ViewBuilder
    private var panelSelector: some View {
        Text("Panel")
            .font(.headline)
            .fixedSize(horizontal: false, vertical: true)
        ForEach(ShellColumnID.allCases, id: \.self) { column in
            Button(column.title) { selectedColumn = column }
                .buttonStyle(.plain)
                .fontWeight(selectedColumn == column ? .bold : .regular)
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
                .background(
                    selectedColumn == column ? Color.accentColor.opacity(0.12) : .clear,
                    in: Capsule()
                )
                .fixedSize(horizontal: false, vertical: true)
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
            if section.id == .conversation, let projection = store.projection {
                MessageStreamView(projection: projection)
                    .frame(minHeight: 180)
            } else {
                stateText(section.state)
            }
            if section.id == .sessions {
                templateLaunchers(availability: availability)
            }
            if section.id == .composer {
                ConversationComposerView(
                    model: conversationComposer,
                    isSendEnabled: availability.isEnabled && isAdvertised(.sendMessage)
                ) {
                    sendDraft(availability: availability)
                }
            }
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
        case .composer: nil
        default: nil
        }
    }

    @ViewBuilder
    private func templateLaunchers(availability: MutationAvailability) -> some View {
        ForEach(templateLauncher.presets) { preset in
            Button {
                guard let session = Self.readySession(in: connectionState) else { return }
                templateLauncher.launch(
                    preset,
                    expectedCursor: store.latestAppliedCursor ?? 0,
                    sessionCapability: session.sessionCapability,
                    submit: templateCommandAction
                )
                conversationComposer.draft = templateLauncher.draft
            } label: {
                HStack {
                    Image(systemName: templateLauncher.selectedPresetID == preset.id
                        ? "largecircle.fill.circle" : "circle")
                    Text(preset.name)
                }
            }
            .disabled(!availability.isEnabled || !isSessionCreateAdvertised)
            .accessibilityLabel("Launch \(preset.name) template")
        }
    }

    private func sendDraft(availability: MutationAvailability) {
        guard let session = Self.readySession(in: connectionState) else { return }
        _ = conversationComposer.send(
            availability: availability,
            canSend: store.projection?.composer.canSend == true,
            expectedCursor: store.latestAppliedCursor ?? 0,
            session: session,
            submit: templateCommandAction
        )
    }

    private var isSessionCreateAdvertised: Bool {
        Self.readySession(in: connectionState)?
            .supportedCommands.contains("session.create") == true
    }

    private func isAdvertised(_ control: ShellMutationControl) -> Bool {
        switch control {
        case .newSession: isSessionCreateAdvertised
        case .sendMessage:
            store.projection?.composer.canSend == true
                && Self.readySession(in: connectionState)?
                    .supportedCommands.contains("chat.send") == true
        }
    }

    private static func readySession(
        in state: NativeConnectionState
    ) -> NativeReadySession? {
        switch state {
        case .ready(let session), .fallback(.ready(let session)):
            session
        default:
            nil
        }
    }

    private func controlTitle(_ control: ShellMutationControl) -> String {
        switch control {
        case .newSession: "New Session"
        case .sendMessage: "Send"
        }
    }
}
