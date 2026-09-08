import AppKit
import BirkinNativeProtocol
import SwiftUI
import UniformTypeIdentifiers

public enum WorkspaceRoute: String, CaseIterable, Identifiable, Sendable {
    case conversation
    case research
    case documents
    case approvals

    public var id: String { rawValue }
    public var title: String {
        switch self {
        case .conversation: "대화"
        case .research: "리서치"
        case .documents: "문서"
        case .approvals: "승인"
        }
    }
    public var symbol: String {
        switch self {
        case .conversation: "bubble.left.and.bubble.right"
        case .research: "doc.text.magnifyingglass"
        case .documents: "doc.richtext"
        case .approvals: "checkmark.shield"
        }
    }

    public static func resolve(
        focus target: ShellFocusTarget,
        navigationIntent: WorkspaceRoute?
    ) -> WorkspaceRoute? {
        if let navigationIntent { return navigationIntent }
        guard case .section(let section) = target else { return nil }
        switch section {
        case .conversation, .composer, .terminal: .conversation
        case .office: .documents
        case .approvals: .approvals
        case .browserAside: .research
        default: nil
        }
    }
}

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
    private let columnWidthAction: (ShellColumnID, CGFloat) -> Void
    private let evidenceSpecimens: [String]
    @ObservedObject private var presentationModel: ShellPresentationModel

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.shellVisualSettings) private var visualSettings
    @State private var selectedColumn: ShellColumnID
    @State private var activeRoute: WorkspaceRoute = .conversation
    @State private var pendingNavigationIntent: WorkspaceRoute?
    @State private var focusedAdditionalSection: ShellSectionID?
    @State private var officeFormat = "docx"
    @State private var officeOutputName = ""
    @State private var officeContent = ""
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
        initialRoute: WorkspaceRoute = .conversation,
        commandError: String? = nil,
        diagnosticsAction: @escaping () -> Void = {},
        mutationAction: @escaping (ShellMutationControl) -> Void = { _ in },
        templateCommandAction: @escaping (NativeCommandRequest) -> Void = { _ in },
        productSurfaceAction: @escaping (ProductSurfaceControl) -> Void = { _ in },
        voiceInputAction: @escaping () -> Void = {},
        columnWidthAction: @escaping (ShellColumnID, CGFloat) -> Void = { _, _ in },
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
        self.columnWidthAction = columnWidthAction
        self.evidenceSpecimens = evidenceSpecimens
        self.presentationModel = presentationModel
        _selectedColumn = State(
            initialValue: presentationModel.target?.column ?? initialColumn
        )
        _activeRoute = State(initialValue: initialRoute)
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
            HStack(spacing: 16) {
                HStack(spacing: 10) {
                    Image("birkin-brand-mark", bundle: .module)
                        .resizable().scaledToFit().frame(width: 38, height: 38)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Birkin").font(.title2.weight(.bold))
                        Text("현재 업무와 검토할 내용을 한곳에서 확인하세요.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
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
                    Label(
                        NativeLocalization.string("Commands"),
                        systemImage: "command"
                    )
                }
                .keyboardShortcut("k", modifiers: .command)
                .accessibilityLabel(NativeLocalization.string(
                    "Open command palette"
                ))
            }
            .padding(.horizontal, 20).padding(.vertical, 14)
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
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: "exclamationmark.triangle.fill")
                    VStack(alignment: .leading, spacing: 2) {
                        Text("작업을 완료하지 못했습니다").font(.subheadline.weight(.semibold))
                        Text(commandError).font(.caption).lineLimit(3)
                        Text("입력과 선택은 유지됩니다. 상태를 확인한 뒤 다시 시도하세요.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                    .foregroundStyle(.red)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 20)
                    .padding(.bottom, 10)
                    .accessibilityLabel("작업 오류: \(commandError)")
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
        .background(workspaceBackground)
        .background { shortcutBindings }
        .contrast(visualSettings.increasedContrast ? 1.25 : 1)
        .transaction { transaction in
            if visualSettings.reduceMotion { transaction.disablesAnimations = true }
        }
        .onChange(of: presentationModel.requestGeneration) { _ in
            if let target = presentationModel.target,
               let route = WorkspaceRoute.resolve(
                    focus: target,
                    navigationIntent: pendingNavigationIntent
               ) {
                activeRoute = route
                pendingNavigationIntent = nil
                if case .section(.browserAside) = target {
                    selectedColumn = .context
                } else {
                    selectedColumn = .primary
                }
            } else if let column = presentationModel.target?.column {
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
                jailedDrop.refuse(reason: "선택한 파일을 열 수 없습니다.")
            }
        }
    }

    private func threeColumnContent(
        _ structure: ShellStructure,
        layout: ShellLayoutPlan,
        availability: MutationAvailability
    ) -> some View {
        HSplitView {
            ForEach(structure.columns, id: \.id) { column in
                let width = layout.width(for: column.id)
                columnView(column, availability: availability)
                    .frame(
                        minWidth: width.minimum,
                        idealWidth: width.ideal,
                        maxWidth: width.maximum,
                        maxHeight: .infinity,
                        alignment: .top
                    )
                    .layoutPriority(width.layoutPriority)
                    .overlay {
                        Rectangle()
                            .stroke(
                                selectedColumn == column.id ? Color.accentColor : .clear,
                                lineWidth: visualSettings.increasedContrast ? 3 : 2
                            )
                            .allowsHitTesting(false)
                    }
                    .accessibilityAddTraits(
                        selectedColumn == column.id ? .isSelected : []
                    )
                    .accessibilityIdentifier("shell-column-\(column.id.rawValue)")
                    .background {
                        ShellColumnWidthProbe {
                            columnWidthAction(column.id, $0)
                        }
                    }
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
    private var shortcutBindings: some View {
        Group {
            Button(NativeLocalization.string("Show Navigation Panel")) {
                focusColumn(.navigation)
            }
            .keyboardShortcut("1", modifiers: .command)
            Button(NativeLocalization.string("Show Conversation Panel")) {
                focusColumn(.primary)
            }
            .keyboardShortcut("2", modifiers: .command)
            Button(NativeLocalization.string("Show Context Panel")) {
                focusColumn(.context)
            }
            .keyboardShortcut("3", modifiers: .command)
            Button(NativeLocalization.string("Show Oldest Approval")) {
                focusApprovals()
            }
            .keyboardShortcut("a", modifiers: [.command, .shift])
        }
        .frame(width: 0, height: 0)
        .clipped()
        .accessibilityHidden(true)
    }

    @ViewBuilder
    private var panelSelector: some View {
        Text(NativeLocalization.string("Panel"))
            .font(.headline)
            .fixedSize(horizontal: false, vertical: true)
        ForEach(ShellColumnID.allCases, id: \.self) { column in
            Button(column.title) { focusColumn(column) }
                .buttonStyle(.plain)
                .accessibilityLabel(NativeLocalization.string(
                    "Show %@ panel",
                    column.title
                ))
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
                Text(columnTitle(column.id))
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
        .accessibilityLabel(NativeLocalization.string(
            "%@ column",
            column.id.title
        ))
        .accessibilitySortPriority(column.id.accessibilitySortPriority)
    }

    private func columnSections(
        _ column: ShellColumn,
        availability: MutationAvailability
    ) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            if column.id == .navigation {
                workspaceNavigation
            }
            ForEach(visibleSections(in: column), id: \.id) { section in
                sectionView(section, availability: availability)
            }
            if column.id == .navigation {
                additionalNavigation
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
            Group {
                if section.id == .conversation, let projection = store.projection {
                    if activeRoute == .research {
                        ResearchReportView(projection: projection)
                    } else {
                        MessageStreamView(projection: projection)
                    }
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
                    canDecide: availability.isEnabled && computerAnswerAdvertised,
                    canExecute: availability.isEnabled && computerExecuteAdvertised,
                    approve: { productSurfaceAction(.computerUseAnswer(decision: "approve")) },
                    reject: { productSurfaceAction(.computerUseAnswer(decision: "reject")) },
                    execute: { productSurfaceAction(.computerUseExecute) }
                )
                } else if section.id == .office,
                      let presentation = OfficePresentation(store: store) {
                OfficeView(
                    presentation: presentation,
                    canCreate: availability.isEnabled && officeCreateAdvertised,
                    canOpen: availability.isEnabled && officeOpenAdvertised,
                    canSelect: availability.isEnabled && officeSelectAdvertised,
                    format: $officeFormat,
                    outputName: $officeOutputName,
                    content: $officeContent,
                    createForm: { productSurfaceAction(.officeCreate(form: $0)) },
                    open: { productSurfaceAction(.officeOpen) },
                    select: { productSurfaceAction(.officeSelect(artifactID: $0)) }
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
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if section.id == .sessions {
                templateLaunchers(availability: availability)
            }
            if section.id == .composer {
                if visualSettings.snapshotRendering {
                    if let reference = jailedDrop.reference {
                        ImportedReferenceChip(reference: reference)
                    } else {
                        Label(
                            NativeLocalization.string("Drop a file to import"),
                            systemImage: "tray.and.arrow.down"
                        )
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
                        Label(
                            NativeLocalization.string("Attach File"),
                            systemImage: "paperclip"
                        )
                    }
                    .disabled(!availability.isEnabled || !isFileImportAdvertised)
                    .keyboardShortcut("o", modifiers: [.command, .shift])
                    .accessibilityLabel(NativeLocalization.string(
                        "Choose a file to import into the workspace jail"
                    ))
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
                Button(NativeLocalization.string("New Terminal")) {
                    requestTerminal(availability: availability)
                }
                    .disabled(!availability.isEnabled || !terminalCreateAdvertised)
                    .accessibilityLabel(NativeLocalization.string(
                        "Request new Python terminal"
                    ))
            }
            if let control = mutationControl(for: section.id) {
                let surfaceEnabled = isAdvertised(control)
                Button(controlTitle(control)) { mutationAction(control) }
                    .disabled(!availability.isEnabled || !surfaceEnabled)
                    .keyboardShortcut("n", modifiers: .command)
                    .accessibilityLabel(controlTitle(control))
                if !availability.isEnabled || !surfaceEnabled {
                    Text(
                        availability.disabledReason
                            ?? NativeLocalization.string(
                                "Not advertised by Python."
                            )
                    )
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(cardBackground, in: RoundedRectangle(cornerRadius: 12))
        .overlay { RoundedRectangle(cornerRadius: 12).stroke(Color(red: 0.84, green: 0.87, blue: 0.90)) }
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
            case .content(let count):
                Text(NativeLocalization.string(
                    count == 1
                        ? "%lld canonical item"
                        : "%lld canonical items",
                    Int64(count)
                ))
            }
        }
        .font(.subheadline)
        .foregroundStyle(.secondary)
        .fixedSize(horizontal: false, vertical: true)
    }

    private func focusColumn(_ column: ShellColumnID) {
        selectedColumn = column
        let target: ShellSectionID = switch column {
        case .navigation: .sessions
        case .primary: .conversation
        case .context: .activity
        }
        presentationModel.focus(.section(target))
        announce(NativeLocalization.string(
            "%@ panel focused",
            column.title
        ))
    }

    private func focusApprovals() {
        activeRoute = .approvals
        selectedColumn = .primary
        presentationModel.focus(.section(.approvals))
        announce(NativeLocalization.string("Oldest approval focused"))
    }

    private func announce(_ message: String) {
        NSAccessibility.post(
            element: NSApp as Any,
            notification: .announcementRequested,
            userInfo: [
                .announcement: message,
                .priority: NSAccessibilityPriorityLevel.high.rawValue,
            ]
        )
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
            .accessibilityLabel(NativeLocalization.string(
                "Launch %@ template",
                preset.name
            ))
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
            Text(NativeLocalization.string("No approvals yet."))
                .font(.subheadline)
                .foregroundStyle(.secondary)
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

    private var workspaceNavigation: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("업무").font(.headline)
            ForEach(WorkspaceRoute.allCases) { route in
                Button {
                    activeRoute = route
                    pendingNavigationIntent = route
                    focusedAdditionalSection = nil
                    selectedColumn = .primary
                    presentationModel.focus(.section(primarySection(for: route)))
                } label: {
                    Label(route.title, systemImage: route.symbol)
                        .frame(maxWidth: .infinity, minHeight: 36, alignment: .leading)
                        .padding(.horizontal, 10)
                        .foregroundStyle(
                            activeRoute == route
                                ? Color(red: 0.09, green: 0.13, blue: 0.17) : .primary
                        )
                        .background(
                            activeRoute == route
                                ? Color(red: 0.88, green: 0.95, blue: 0.93) : .clear,
                            in: RoundedRectangle(cornerRadius: 10)
                        )
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("workspace-route-\(route.rawValue)")
                .accessibilityAddTraits(activeRoute == route ? .isSelected : [])
            }
        }
    }

    private var additionalNavigation: some View {
        DisclosureGroup("더보기") {
            VStack(alignment: .leading, spacing: 8) {
                Button("터미널") { focusSection(.terminal) }
                Button("작업 메모") { focusSection(.workingMemory) }
                Button("리서치 브라우저") { focusSection(.browserAside) }
                Button("화면 작업") { focusSection(.computerUse) }
            }
            .buttonStyle(.plain)
            .padding(.top, 8)
        }
        .font(.subheadline)
    }

    private func visibleSections(in column: ShellColumn) -> [ShellSection] {
        let ids: Set<ShellSectionID>
        switch column.id {
        case .navigation:
            ids = [.sessions]
        case .primary:
            ids = switch activeRoute {
            case .conversation: [.conversation, .composer]
            case .research: [.conversation]
            case .documents: [.office]
            case .approvals: [.approvals]
            }
        case .context:
            ids = switch activeRoute {
            case .conversation: [.activity]
            case .research: [.browserAside, .activity]
            case .documents: [.approvals, .activity]
            case .approvals: [.activity]
            }
        }
        let candidates = (column.id == .primary
            && (activeRoute == .documents || activeRoute == .approvals))
            ? ShellStructure(store: store).columns.flatMap(\.sections)
            : column.sections
        return candidates.filter {
            ids.contains($0.id) || $0.id == focusedAdditionalSection
        }
    }

    private func primarySection(for route: WorkspaceRoute) -> ShellSectionID {
        switch route {
        case .conversation, .research: .conversation
        case .documents: .office
        case .approvals: .approvals
        }
    }

    private func columnTitle(_ column: ShellColumnID) -> String {
        switch column {
        case .navigation: "업무"
        case .primary: activeRoute.title
        case .context: "검토"
        }
    }

    private func focusSection(_ section: ShellSectionID) {
        focusedAdditionalSection = section
        if let route = WorkspaceRoute.resolve(
            focus: .section(section), navigationIntent: nil
        ) { activeRoute = route }
        selectedColumn = section == .workingMemory ? .navigation
            : (section == .browserAside || section == .computerUse ? .context : .primary)
        presentationModel.focus(.section(section))
    }

    private var computerAnswerAdvertised: Bool {
        Self.readySession(in: connectionState)?
            .supportedCommands.contains("computer.answer") == true
    }

    private var computerExecuteAdvertised: Bool {
        Self.readySession(in: connectionState)?
            .supportedCommands.contains("computer.execute") == true
    }

    private var officeSelectAdvertised: Bool {
        Self.readySession(in: connectionState)?
            .supportedCommands.contains("office.select") == true
    }

    private var workspaceBackground: Color {
        colorScheme == .dark
            ? Color(nsColor: .windowBackgroundColor)
            : Color(red: 0.96, green: 0.97, blue: 0.98)
    }

    private var cardBackground: Color {
        colorScheme == .dark
            ? Color(nsColor: .controlBackgroundColor)
            : .white
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
        case .newSession: NativeLocalization.string("New Session")
        }
    }
}

@MainActor
private final class ShellColumnWidthView: NSView {
    var report: (CGFloat) -> Void = { _ in }

    override func layout() {
        super.layout()
        report(bounds.width)
    }
}

private struct ShellColumnWidthProbe: NSViewRepresentable {
    let report: (CGFloat) -> Void

    func makeNSView(context _: Context) -> ShellColumnWidthView {
        let view = ShellColumnWidthView()
        view.report = report
        return view
    }

    func updateNSView(_ view: ShellColumnWidthView, context _: Context) {
        view.report = report
        view.needsLayout = true
    }
}
