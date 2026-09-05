import BirkinNativeProtocol
import SwiftUI
import UniformTypeIdentifiers

public struct NativeShellView: View {
    private let store: NativeProjectionStore
    private let connectionState: NativeConnectionState
    private let now: Date
    private let commandError: String?
    private let diagnosticsAction: () -> Void
    private let mutationAction: (ShellMutationControl) -> Void
    private let templateCommandAction: (NativeCommandRequest) -> Void
    private let productSurfaceAction: (ProductSurfaceControl) -> Void
    private let voiceInputAction: () -> Void
    private let evidenceSpecimens: [String]
    @ObservedObject private var presentationModel: ShellPresentationModel

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.shellVisualSettings) private var visualSettings
    @State private var selectedColumn: ShellColumnID
    @State private var showsAttachmentPicker = false
    @State private var showsCommandPalette = false
    @StateObject private var templateLauncher: TemplateLauncherModel
    @StateObject private var conversationComposer: ConversationComposerModel
    @StateObject private var jailedDrop: JailedDropModel
    @StateObject private var voiceInput: VoiceInputModel
    @StateObject private var terminalControls: TerminalControlModel
    @StateObject private var activityFilter: ActivityFilterModel

    public init(
        store: NativeProjectionStore,
        connectionState: NativeConnectionState,
        now: Date = Date(),
        initialColumn: ShellColumnID = .navigation,
        commandError: String? = nil,
        diagnosticsAction: @escaping () -> Void = {},
        mutationAction: @escaping (ShellMutationControl) -> Void = { _ in },
        templateCommandAction: @escaping (NativeCommandRequest) -> Void = { _ in },
        productSurfaceAction: @escaping (ProductSurfaceControl) -> Void = { _ in },
        voiceInputAction: @escaping () -> Void = {},
        evidenceSpecimens: [String] = [],
        jailedDrop: JailedDropModel = JailedDropModel(),
        presentationModel: ShellPresentationModel = ShellPresentationModel(),
        makeSessionID: @escaping () -> String = { UUID().uuidString.lowercased() }
    ) {
        self.store = store
        self.connectionState = connectionState
        self.now = now
        self.commandError = commandError
        self.diagnosticsAction = diagnosticsAction
        self.mutationAction = mutationAction
        self.templateCommandAction = templateCommandAction
        self.productSurfaceAction = productSurfaceAction
        self.voiceInputAction = voiceInputAction
        self.evidenceSpecimens = evidenceSpecimens
        self.presentationModel = presentationModel
        _selectedColumn = State(
            initialValue: presentationModel.target?.column ?? initialColumn
        )
        _templateLauncher = StateObject(wrappedValue: TemplateLauncherModel(
            presets: Self.readySession(in: connectionState)?.sessionPresets ?? [],
            makeSessionID: makeSessionID
        ))
        _conversationComposer = StateObject(wrappedValue: ConversationComposerModel())
        _jailedDrop = StateObject(wrappedValue: jailedDrop)
        _voiceInput = StateObject(wrappedValue: VoiceInputModel())
        _terminalControls = StateObject(wrappedValue: TerminalControlModel())
        _activityFilter = StateObject(wrappedValue: ActivityFilterModel())
    }

    public var body: some View {
        let structure = ShellStructure(store: store)
        let availability = MutationAvailability(state: connectionState, now: now)
        VStack(spacing: 0) {
            HStack {
                ConnectionStatusPill(
                    presentation: ConnectionPresentation(state: connectionState),
                    diagnosticsAction: diagnosticsAction
                )
                .id(ShellFocusTarget.connection)
                .background(focusVisibilityProbe(for: .connection))
                Spacer()
                Button {
                    showsCommandPalette = true
                } label: {
                    Label("명령", systemImage: "command")
                }
                .keyboardShortcut("k", modifiers: .command)
                .accessibilityLabel("명령 팔레트 열기")
            }
            .padding(12)
            .overlay {
                HStack(spacing: 24) {
                    ForEach(evidenceSpecimens, id: \.self) { specimen in
                        Text(specimen)
                            .font(.title2.weight(.bold))
                            .fixedSize()
                    }
                }
                .frame(maxWidth: .infinity)
                .accessibilityIdentifier("journey-cjk-specimens")
            }
            if let commandError {
                Text(commandError)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .lineLimit(3)
                    .padding(.horizontal, 12)
                    .padding(.bottom, 8)
                    .accessibilityLabel("명령 오류: \(commandError)")
            }
            Divider()
            GeometryReader { geometry in
                let layout = ShellLayoutPlan(
                    windowWidth: geometry.size.width,
                    dynamicTypeSize: dynamicTypeSize
                )
                if layout.mode == .panelNavigation {
                    adaptiveContent(structure, availability: availability)
                } else {
                    threeColumnContent(
                        structure,
                        layout: layout,
                        availability: availability
                    )
                }
            }
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .contrast(visualSettings.increasedContrast ? 1.25 : 1)
        .transaction { transaction in
            if visualSettings.reduceMotion { transaction.disablesAnimations = true }
        }
        .onChange(of: presentationModel.requestGeneration) { _ in
            if let column = presentationModel.target?.column {
                selectedColumn = column
            }
        }
        .sheet(isPresented: $showsCommandPalette) {
            CommandPaletteView(model: CommandPaletteModel(
                advertisedCommands: Self.readySession(in: connectionState)?
                    .supportedCommands ?? []
            )) { item in
                selectPaletteCommand(item.commandType)
            }
        }
        .fileImporter(
            isPresented: $showsAttachmentPicker,
            allowedContentTypes: [.data],
            allowsMultipleSelection: false
        ) { result in
            switch result {
            case .success(let urls):
                importDroppedURLs(
                    urls,
                    availability: MutationAvailability(state: connectionState, now: now)
                )
            case .failure(let error):
                let cocoaError = error as NSError
                guard cocoaError.domain != NSCocoaErrorDomain
                        || cocoaError.code != NSUserCancelledError else { return }
                jailedDrop.refuse(reason: "The selected file could not be opened.")
            }
        }
    }

    private func threeColumnContent(
        _ structure: ShellStructure,
        layout: ShellLayoutPlan,
        availability: MutationAvailability
    ) -> some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(Array(structure.columns.enumerated()), id: \.element.id) { index, column in
                let width = layout.width(for: column.id)
                columnView(column, availability: availability)
                    .frame(
                        minWidth: width.minimum,
                        idealWidth: width.ideal,
                        maxWidth: .infinity,
                        maxHeight: .infinity,
                        alignment: .top
                    )
                    .layoutPriority(width.layoutPriority)
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
        Text("패널")
            .font(.headline)
            .fixedSize(horizontal: false, vertical: true)
        ForEach(ShellColumnID.allCases, id: \.self) { column in
            Button(column.title) { selectedColumn = column }
                .buttonStyle(.plain)
                .accessibilityLabel("\(column.title) 패널 보기")
                .accessibilityAddTraits(selectedColumn == column ? .isSelected : [])
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
        ScrollViewReader { proxy in
            VStack(alignment: .leading, spacing: 0) {
                Text(column.id.title)
                    .font(.title2.bold())
                    .fixedSize(horizontal: false, vertical: true)
                    .padding([.horizontal, .top])
                if visualSettings.snapshotRendering {
                    columnSections(column, availability: availability)
                } else {
                    ScrollView {
                        columnSections(column, availability: availability)
                    }
                }
            }
            .onChange(of: presentationModel.requestGeneration) { _ in
                guard let target = presentationModel.target,
                      target.column == column.id else { return }
                proxy.scrollTo(target, anchor: .center)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("\(column.id.title) column")
        .accessibilitySortPriority(column.id.accessibilitySortPriority)
    }

    private func columnSections(
        _ column: ShellColumn,
        availability: MutationAvailability
    ) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(column.sections, id: \.id) { section in
                sectionView(section, availability: availability)
            }
        }
        .padding()
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
            } else if section.id == .workingMemory, let projection = store.projection {
                WorkingMemoryView(
                    presentation: WorkingMemoryPresentation(
                        projection: projection.workingMemory
                    ),
                    clearPresentation: WorkingMemoryClearPresentation(
                        sessionID: projection.sessionID
                    ),
                    canClear: availability.isEnabled && isWorkingMemoryAdvertised
                ) {
                    clearWorkingMemory(availability: availability)
                }
            } else if section.id == .approvals {
                approvalCards(availability: availability)
            } else if section.id == .activity {
                ActivityListView(items: activityItems, filter: activityFilter)
            } else if section.id == .browserAside,
                      let presentation = BrowserAsidePresentation(store: store) {
                BrowserAsideView(
                    presentation: presentation,
                    start: availability.isEnabled && browserStartAdvertised
                        ? { productSurfaceAction(.browserStart) } : nil,
                    navigate: availability.isEnabled && browserNavigateAdvertised
                        ? { productSurfaceAction(.browserNavigate(url: $0)) } : nil
                )
            } else if section.id == .computerUse,
                      let presentation = ComputerUsePresentation(store: store, now: now) {
                ComputerUseStatusView(
                    presentation: presentation,
                    canDecide: availability.isEnabled && approvalAnswerAdvertised,
                    approve: { productSurfaceAction(.computerUseApproveOnce) },
                    reject: { productSurfaceAction(.computerUseReject) }
                )
            } else if section.id == .office,
                      let presentation = OfficePresentation(store: store) {
                OfficeView(
                    presentation: presentation,
                    canCreate: availability.isEnabled && officeCreateAdvertised,
                    canOpen: availability.isEnabled && officeOpenAdvertised,
                    create: { productSurfaceAction(.officeNew) },
                    open: { productSurfaceAction(.officeOpen) }
                )
            } else if section.id == .terminal,
                      let terminal = store.projection?.terminals.first {
                TerminalView(
                    terminal: terminal,
                    canMutate: terminalMutationEnabled(availability)
                ) { data in
                    sendTerminalInput(data, terminal: terminal, availability: availability)
                } interrupt: {
                    interruptTerminal(terminal, availability: availability)
                } close: {
                    closeTerminal(terminal, availability: availability)
                }
            } else {
                stateText(section.state)
            }
            if section.id == .sessions {
                templateLaunchers(availability: availability)
            }
            if section.id == .composer {
                if visualSettings.snapshotRendering {
                    if let reference = jailedDrop.reference {
                        ImportedReferenceChip(reference: reference)
                    } else {
                        Label("가져올 파일을 놓으세요", systemImage: "tray.and.arrow.down")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(8)
                            .overlay {
                                RoundedRectangle(cornerRadius: 8)
                                    .stroke(
                                        .secondary.opacity(0.4),
                                        style: StrokeStyle(lineWidth: 1, dash: [4])
                                    )
                            }
                    }
                } else {
                    Button {
                        showsAttachmentPicker = true
                    } label: {
                        Label("파일 첨부", systemImage: "paperclip")
                    }
                    .disabled(!availability.isEnabled || !isFileImportAdvertised)
                    .keyboardShortcut("o", modifiers: [.command, .shift])
                    .accessibilityLabel("안전한 작업공간으로 가져올 파일 선택")
                    JailedDropZone(model: jailedDrop) { urls in
                        importDroppedURLs(urls, availability: availability)
                    }
                    ConversationComposerView(
                        model: conversationComposer,
                        isSendEnabled: availability.isEnabled && isChatSendAdvertised
                    ) {
                        sendDraft(availability: availability)
                    }
                    if let session = Self.readySession(in: connectionState) {
                        VoiceInputControl(
                            model: voiceInput,
                            session: session,
                            beginCapture: voiceInputAction
                        )
                    }
                }
            }
            if section.id == .terminal, store.projection?.terminals.isEmpty != false {
                Button("새 터미널") { requestTerminal(availability: availability) }
                    .disabled(!availability.isEnabled || !terminalCreateAdvertised)
                    .accessibilityLabel("새 Python 터미널 요청")
            }
            if let control = mutationControl(for: section.id) {
                let surfaceEnabled = isAdvertised(control)
                Button(controlTitle(control)) { mutationAction(control) }
                    .disabled(!availability.isEnabled || !surfaceEnabled)
                    .keyboardShortcut("n", modifiers: .command)
                    .accessibilityLabel(controlTitle(control))
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
        .accessibilityElement(children: .contain)
        .accessibilityLabel(section.id.title)
        .id(ShellFocusTarget.section(section.id))
        .background(
            focusVisibilityProbe(for: .section(section.id))
        )
    }

    private func focusVisibilityProbe(for target: ShellFocusTarget) -> some View {
        ShellFocusVisibilityProbe { isVisible in
            presentationModel.reportVisibility(
                target: target,
                isVisible: isVisible
            )
        }
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

    private func selectPaletteCommand(_ commandType: String) {
        switch commandType.split(separator: ".").first {
        case "session", "memory": selectedColumn = .navigation
        case "chat", "terminal", "file": selectedColumn = .primary
        default: selectedColumn = .context
        }
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
            .accessibilityLabel("\(preset.name) 템플릿 시작")
        }
    }

    private var activityItems: [NativeJSONObject] {
        store.projection?.panels.first(where: { $0.key == "activity_logs" })?.items ?? []
    }

    @ViewBuilder
    private func approvalCards(availability: MutationAvailability) -> some View {
        let items = store.projection?.panels.first(where: { $0.key == "approvals" })?.items ?? []
        let cards = items.compactMap(ApprovalCardPresentation.init)
        if cards.isEmpty {
            Text("대기 중인 승인 요청이 없습니다.").font(.subheadline).foregroundStyle(.secondary)
        } else {
            ForEach(cards) { card in
                ApprovalCardView(
                    presentation: card,
                    canDecide: availability.isEnabled && approvalAnswerAdvertised,
                    approve: { submitApproval(card, decision: .approve, availability: availability) },
                    reject: { submitApproval(card, decision: .reject, availability: availability) }
                )
            }
        }
    }

    private func submitApproval(
        _ card: ApprovalCardPresentation,
        decision: ApprovalDecision,
        availability: MutationAvailability
    ) -> Bool {
        guard let session = Self.readySession(in: connectionState) else { return false }
        return card.submit(
            decision, availability: availability,
            commandAdvertised: approvalAnswerAdvertised,
            expectedCursor: store.latestAppliedCursor ?? 0,
            sessionCapability: session.sessionCapability,
            submit: templateCommandAction
        )
    }

    private func importDroppedURLs(
        _ urls: [URL],
        availability: MutationAvailability
    ) {
        guard let session = Self.readySession(in: connectionState) else { return }
        _ = jailedDrop.accept(
            urls: urls,
            availability: availability,
            expectedCursor: store.latestAppliedCursor ?? 0,
            session: session,
            submit: templateCommandAction
        )
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

    private func clearWorkingMemory(availability: MutationAvailability) {
        guard availability.isEnabled,
              let session = Self.readySession(in: connectionState),
              isWorkingMemoryAdvertised,
              let memory = store.projection?.workingMemory else { return }
        let commandID = "memory-clear-\(UUID().uuidString.lowercased())"
        templateCommandAction(NativeCommandRequest(
            frameID: "frame-\(commandID)",
            commandID: commandID,
            expectedCursor: store.latestAppliedCursor ?? 0,
            commandType: "memory.write",
            payload: [
                "op": .string("clear"),
                "expected_revision": .int(memory.revision),
            ],
            sessionCapability: session.sessionCapability,
            viewID: "working-memory"
        ))
    }

    private func requestTerminal(availability: MutationAvailability) {
        guard availability.isEnabled,
              let session = Self.readySession(in: connectionState),
              terminalCreateAdvertised else { return }
        _ = terminalControls.requestTerminal(
            expectedCursor: store.latestAppliedCursor ?? 0,
            sessionCapability: session.sessionCapability,
            submit: templateCommandAction
        )
    }

    private func sendTerminalInput(
        _ data: String,
        terminal: NativeTerminalProjection,
        availability: MutationAvailability
    ) {
        guard terminalMutationEnabled(availability),
              let session = Self.readySession(in: connectionState) else { return }
        _ = terminalControls.sendInput(
            data, terminal: terminal,
            expectedCursor: store.latestAppliedCursor ?? 0,
            sessionCapability: session.sessionCapability,
            submit: templateCommandAction
        )
    }

    private func interruptTerminal(
        _ terminal: NativeTerminalProjection,
        availability: MutationAvailability
    ) {
        guard terminalMutationEnabled(availability),
              let session = Self.readySession(in: connectionState) else { return }
        _ = terminalControls.interrupt(
            terminal: terminal, expectedCursor: store.latestAppliedCursor ?? 0,
            sessionCapability: session.sessionCapability,
            submit: templateCommandAction
        )
    }

    private func closeTerminal(
        _ terminal: NativeTerminalProjection,
        availability: MutationAvailability
    ) {
        guard terminalMutationEnabled(availability),
              let session = Self.readySession(in: connectionState) else { return }
        _ = terminalControls.close(
            terminal: terminal, confirmed: true,
            expectedCursor: store.latestAppliedCursor ?? 0,
            sessionCapability: session.sessionCapability,
            submit: templateCommandAction
        )
    }

    private var approvalAnswerAdvertised: Bool {
        Self.readySession(in: connectionState)?
            .supportedCommands.contains("approval.answer") == true
    }

    private var browserStartAdvertised: Bool {
        Self.readySession(in: connectionState)?
            .supportedCommands.contains("browser.start") == true
    }

    private var browserNavigateAdvertised: Bool {
        Self.readySession(in: connectionState)?
            .supportedCommands.contains("browser.navigate") == true
    }

    private var officeCreateAdvertised: Bool {
        Self.readySession(in: connectionState)?
            .supportedCommands.contains("office.create") == true
    }

    private var officeOpenAdvertised: Bool {
        Self.readySession(in: connectionState)?
            .supportedCommands.contains("office.open") == true
    }

    private var terminalCreateAdvertised: Bool {
        Self.readySession(in: connectionState)?
            .supportedCommands.contains("terminal.create") == true
    }

    private func terminalMutationEnabled(_ availability: MutationAvailability) -> Bool {
        guard availability.isEnabled,
              let commands = Self.readySession(in: connectionState)?.supportedCommands else {
            return false
        }
        return commands.isSuperset(of: [
            "terminal.input", "terminal.signal", "terminal.close",
        ])
    }

    private var isFileImportAdvertised: Bool {
        Self.readySession(in: connectionState)?
            .supportedCommands.contains("file.import") == true
    }

    private var isWorkingMemoryAdvertised: Bool {
        Self.readySession(in: connectionState)?
            .supportedCommands.contains("memory.write") == true
    }

    private var isSessionCreateAdvertised: Bool {
        Self.readySession(in: connectionState)?
            .supportedCommands.contains("session.create") == true
    }

    private var isChatSendAdvertised: Bool {
        store.projection?.composer.canSend == true
            && Self.readySession(in: connectionState)?
                .supportedCommands.contains("chat.send") == true
    }

    private func isAdvertised(_ control: ShellMutationControl) -> Bool {
        switch control {
        case .newSession: isSessionCreateAdvertised
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
        }
    }
}
