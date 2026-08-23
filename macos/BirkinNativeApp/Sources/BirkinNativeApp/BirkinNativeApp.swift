import AppKit
import BirkinNativeProtocol
import BirkinNativeShell
import CryptoKit
import SwiftUI

public enum BirkinApplicationConfiguration {
    public static let bundleIdentifier = "com.birkin.native"
    public static let version = BirkinVersion.packageVersion
    public static let build = "1"
    public static let windowTitle = "Birkin"
    public static let socketEnvironmentKey = "BIRKIN_NATIVE_SOCKET"
    public static let screenshotEnvironmentKey = "BIRKIN_NATIVE_SCREENSHOT"
}

@MainActor
public final class BirkinApplicationRuntime: ObservableObject {
    public let store = NativeProjectionStore()
    public let presentationModel = ShellPresentationModel()
    /// Jailed drag-and-drop state. The runtime owns it because only the
    /// command receipt carries Python's canonical import reference.
    public let jailedDrop = JailedDropModel()
    @Published public private(set) var connectionState: NativeConnectionState = .disconnected
    @Published public private(set) var lastCommandError: String?

    private var socketPath: String?
    private let ownedBridge: OwnedBridgeConfiguration?
    private var supervisor: OwnedBridgeSupervisor?
    private let screenshotPath: String?
    private let reconnectClock: any NativeReconnectClock
    private let randomUnit: NativeReconnectScheduler.RandomUnit
    private let emitEvent: @Sendable (String) -> Void
    private let windowCapture: PackagedWindowCapture
    private let transport = NativeTransportActor()
    private var scheduler: NativeReconnectScheduler?
    private var listener: Task<Void, Never>?
    private var commandSubmitter: (@Sendable (NativeCommandRequest) throws -> Void)?
    private var started = false
    private var connectionGeneration = 0
    private var correlatedCommands: [String: CorrelatedCommand] = [:]
    private var terminationSources: [DispatchSourceSignal] = []

    public init(
        socketPath: String? = ProcessInfo.processInfo.environment[
            BirkinApplicationConfiguration.socketEnvironmentKey
        ],
        screenshotPath: String? = ProcessInfo.processInfo.environment[
            BirkinApplicationConfiguration.screenshotEnvironmentKey
        ],
        ownedBridge: OwnedBridgeConfiguration? = OwnedBridgeConfiguration.discovered(),
        reconnectClock: any NativeReconnectClock = NativeContinuousReconnectClock(),
        randomUnit: @escaping NativeReconnectScheduler.RandomUnit = {
            Double.random(in: 0...1)
        },
        windowCapture: PackagedWindowCapture = PackagedWindowCapture(),
        emit: @escaping @Sendable (String) -> Void = BirkinApplicationRuntime.standardEvent
    ) {
        self.socketPath = socketPath
        self.ownedBridge = ownedBridge
        self.screenshotPath = screenshotPath
        self.reconnectClock = reconnectClock
        self.randomUnit = randomUnit
        self.windowCapture = windowCapture
        self.emitEvent = emit
    }

    public func start() async {
        guard !started else { return }
        started = true
        if socketPath == nil {
            observeTermination()
            startOwnedBridge()
        } else {
            emit("bridge-attached kind=external")
        }
        guard socketPath != nil else {
            emit("disconnected reason=no-endpoint")
            return
        }
        scheduler = NativeReconnectScheduler(
            clock: reconnectClock,
            randomUnit: randomUnit,
            reconnect: { [weak self] in
                guard let self else { return true }
                return await self.connect(replaying: true)
            }
        )
        if !(await connect(replaying: false)) {
            await scheduleReconnect(reason: "initial connection failed")
        }
    }

    /// Terminate the bridge this application owns even when the process is
    /// asked to quit by a signal rather than by the user interface.
    private func observeTermination() {
        guard terminationSources.isEmpty else { return }
        for number in [SIGTERM, SIGINT] {
            signal(number, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: number, queue: .main)
            source.setEventHandler { [weak self] in
                MainActor.assumeIsolated {
                    self?.stop()
                    exit(0)
                }
            }
            source.resume()
            terminationSources.append(source)
        }
    }

    /// Start the bridge this application owns and adopt the endpoint it
    /// announces. An externally managed bridge is never touched.
    private func startOwnedBridge() {
        guard let ownedBridge else {
            emit("bridge-unavailable \(OwnedBridgeConfiguration.discoveryDiagnostic())")
            return
        }
        let supervisor = OwnedBridgeSupervisor(spawn: { [weak self] in
            let launched = try OwnedBridgeLauncher.launch(ownedBridge) { pid, status in
                Task { @MainActor in self?.ownedBridgeExited(pid: pid, status: status) }
            }
            self?.socketPath = launched.socketPath
            return launched.process
        })
        self.supervisor = supervisor
        guard supervisor.startOwnedIfNeeded() else {
            emit("bridge-launch-failed reason=\(supervisor.state)")
            return
        }
        if case .runningOwned(let pid) = supervisor.state {
            let owner = ProcessInfo.processInfo.environment["BIRKIN_NATIVE_OWNER_TOKEN"]
                ?? "unscoped"
            emit(
                "bridge-started kind=owned pid=\(pid) executable=\(ownedBridge.executable)"
                    + " owner_sha256=\(Self.ownershipCorrelationDigest(owner))"
            )
        }
    }

    private func ownedBridgeExited(pid: Int32, status: Int32) {
        guard let supervisor, started else { return }
        supervisor.observeExit(pid: pid, status: status)
        switch supervisor.state {
        case .runningOwned(let replacementPID):
            let owner = ProcessInfo.processInfo.environment["BIRKIN_NATIVE_OWNER_TOKEN"]
                ?? "unscoped"
            emit(
                "bridge-restarted kind=owned pid=\(replacementPID)"
                    + " owner_sha256=\(Self.ownershipCorrelationDigest(owner))"
            )
        case .stopped(let reason): emit("bridge-stopped reason=\(reason)")
        case .attachedExternal, .idle: break
        }
    }

    public func stop() {
        started = false
        supervisor?.shutdown()
        supervisor = nil
        connectionGeneration += 1
        listener?.cancel()
        listener = nil
        commandSubmitter = nil
        correlatedCommands.removeAll()
        connectionState = .disconnected
        Task { await transport.apply(.disconnect) }
    }

    private func connect(replaying: Bool) async -> Bool {
        guard started, let socketPath else { return false }
        connectionState = .connecting
        emit(replaying ? "reconnect-attempt transport=uds" : "connecting transport=uds")
        do {
            let subscription = try await transport.openProjectionSubscriptionUDS(
                socketPath: socketPath,
                hello: NativeHello(
                    client: "birkin-macos",
                    clientVersion: BirkinApplicationConfiguration.version,
                    clientBuild: BirkinApplicationConfiguration.build,
                    surface: "macos",
                    viewID: "main"
                ),
                surfaceRevisions: store.requestedSurfaceRevisions.isEmpty
                    ? nil : store.requestedSurfaceRevisions,
                replaying: replaying
            )
            if subscription.replaying {
                connectionState = .replaying(subscription.session)
                emit("replaying session=\(subscription.session.currentSessionID) after_cursor=0")
            }
            try store.apply(snapshot: subscription.snapshot)
            if subscription.replaying {
                await transport.replayCompleted()
            }
            connectionState = await transport.state
            commandSubmitter = subscription.submit
            connectionGeneration += 1
            let generation = connectionGeneration
            listen(to: subscription.messages, generation: generation)
            try await renderConfiguredEvidence(session: subscription.session)
            if replaying {
                emit(
                    "replayed session=\(subscription.session.currentSessionID) cursor=\(store.latestAppliedCursor ?? -1)"
                )
            } else {
                emit(
                    "connected transport=uds session=\(subscription.session.currentSessionID) "
                        + "cursor=\(store.latestAppliedCursor ?? -1) "
                        + "conversation=\(store.projection?.conversation.count ?? 0)"
                )
            }
            return true
        } catch {
            connectionState = .failed(reason: String(describing: error))
            emit("connect-failed reason=\(String(describing: error))")
            return false
        }
    }

    private func listen(
        to messages: AsyncThrowingStream<NativeEnvelope, any Error>,
        generation: Int
    ) {
        listener?.cancel()
        listener = Task { [weak self] in
            do {
                for try await message in messages {
                    guard let self, self.started, generation == self.connectionGeneration else {
                        return
                    }
                    try await self.apply(message)
                }
                guard let self else { return }
                await self.connectionLost(
                    reason: "projection stream ended", generation: generation
                )
            } catch {
                guard let self else { return }
                await self.connectionLost(
                    reason: String(describing: error), generation: generation
                )
            }
        }
    }

    public func submit(_ request: NativeCommandRequest) {
        Task { [weak self] in
            try? await self?.submitAwaitingTransport(request)
        }
    }

    func submitAwaitingTransport(_ request: NativeCommandRequest) async throws {
        guard let commandSubmitter else {
            let reason = "Command transport is not connected."
            lastCommandError = reason
            throw NativeTransportError(reason)
        }
        lastCommandError = nil
        correlate(request)
        do {
            try await Task.detached {
                try commandSubmitter(request)
            }.value
        } catch {
            let reason = String(describing: error).prefix(300).description
            lastCommandError = reason
            emit("command-submit-failed id=\(request.frameID) reason=\(reason)")
            throw error
        }
    }

    /// The process id of the bridge this application owns, if any.
    public var ownedBridgeProcessIdentifier: Int32? {
        switch supervisor?.state {
        case .runningOwned(let pid): pid
        default: nil
        }
    }

    /// Emit one scripted-QA line on the same channel the shell uses.
    func emitJourney(_ message: String) { emit(message) }

    public func showDiagnostics() {
        emit("diagnostics state=\(String(describing: connectionState))")
    }

    public func submit(_ control: ShellMutationControl) {
        guard let session = readySession else {
            lastCommandError = "Command transport is not ready."
            return
        }
        submit(command(for: control, session: session))
    }

    func command(
        for control: ShellMutationControl,
        session: NativeReadySession
    ) -> NativeCommandRequest {
        let commandType: String
        let payload: NativeJSONObject
        switch control {
        case .newSession:
            commandType = "session.create"
            payload = ["session_id": .string(UUID().uuidString.lowercased())]
        }
        return request(
            commandType: commandType,
            payload: payload,
            session: session,
            viewID: "shell-control"
        )
    }

    public func submit(_ control: ProductSurfaceControl) {
        guard let session = readySession else {
            lastCommandError = "Command transport is not ready."
            return
        }
        switch control {
        case .browserStart:
            submit(BrowserCommandFactory.start(store: store, session: session))
        case .browserNavigate(let url):
            guard let request = BrowserCommandFactory.navigate(
                to: url, store: store, session: session
            ) else {
                lastCommandError = "Browser navigation needs an address and a live private profile."
                return
            }
            submit(request)
        case .computerUseApproveOnce, .computerUseReject:
            guard let surface = store.surface(named: "computer_use"),
                  case .object(let consent) = surface.payload["consent"],
                  case .string(let approvalID) = consent["approval_id"] else {
                lastCommandError = "Computer Use approval is unavailable."
                return
            }
            submit(request(
                commandType: "approval.answer",
                payload: [
                    "approval_id": .string(approvalID),
                    "decision": .string(control == .computerUseApproveOnce ? "approve" : "reject"),
                ],
                session: session, viewID: "computer-use"
            ))
        case .officeNew:
            submit(request(
                commandType: "office.create",
                payload: [
                    "format": .string("docx"),
                    // The canonical document service accepts only the keys its
                    // adapter declares; a title key is refused for docx.
                    "content": .object([
                        "paragraphs": .array([
                            .string("Created from the Birkin macOS shell."),
                        ]),
                    ]),
                    "output_name": .string("birkin-document.docx"),
                ],
                session: session, viewID: "office"
            ))
        case .officeOpen:
            guard let surface = store.surface(named: "office"),
                  case .array(let documents) = surface.payload["documents"],
                  case .object(let artifact) = documents.first else {
                lastCommandError = "No Office document is available to open."
                return
            }
            submit(request(
                commandType: "office.open", payload: ["artifact": .object(artifact)],
                session: session, viewID: "office"
            ))
        }
    }

    public func beginVoiceInput() {
        lastCommandError = "Voice input capture is not available in this build."
    }

    private var readySession: NativeReadySession? {
        switch connectionState {
        case .ready(let session), .fallback(.ready(let session)):
            return session
        default:
            return nil
        }
    }

    private func request(
        commandType: String,
        payload: NativeJSONObject,
        session: NativeReadySession,
        viewID: String
    ) -> NativeCommandRequest {
        let commandID = "app-\(UUID().uuidString.lowercased())"
        return NativeCommandRequest(
            frameID: "frame-\(commandID)", commandID: commandID,
            expectedCursor: store.latestAppliedCursor ?? 0,
            commandType: commandType, payload: payload,
            sessionCapability: session.sessionCapability, viewID: viewID
        )
    }

    private func apply(_ message: NativeEnvelope) async throws {
        switch message.kind {
        case .event:
            try store.apply(event: message)
            let eventType: String
            if case .string(let value) = message.body["type"] {
                eventType = value
            } else {
                eventType = "unknown"
            }
            let commandCorrelation: String
            if case .string(let commandID) = message.body["command_id"] {
                commandCorrelation = " command_id=\(commandID)"
            } else {
                commandCorrelation = ""
            }
            let subjectCorrelation: String
            if case .object(let payload) = message.body["payload"],
               case .string(let subjectSessionID) = payload["session_id"] {
                subjectCorrelation = " subject_session_id=\(subjectSessionID)"
            } else {
                subjectCorrelation = ""
            }
            emit(
                "projection-event type=\(eventType)\(commandCorrelation)"
                    + "\(subjectCorrelation) cursor=\(store.latestAppliedCursor ?? -1)"
            )
        case .snapshot:
            try store.apply(snapshot: message)
        case .surfaceEvent, .surfaceSnapshot:
            try store.apply(surface: message)
            if case .string(let surfaceName) = message.body["surface"] {
                emit("surface-applied name=\(surfaceName)")
                // Only claim a rendered panel when that panel is projected and
                // the produced image actually carries content.
                if let session = readySession,
                   store.surface(named: surfaceName) != nil,
                   try await renderConfiguredEvidence(session: session) {
                    emit("surface-rendered name=\(surfaceName)")
                }
            }
            if case .replayRequired = store.status {
                throw BirkinApplicationRuntimeError.replayRequired
            }
        case .capabilityRenewed:
            try await transport.acceptCapabilityRenewal(message)
            connectionState = await transport.state
        case .receipt:
            lastCommandError = nil
            switch resolveCorrelation(of: message) {
            case .terminalCreate: installTerminalLease(from: message)
            case .fileImport: applyImportResult(from: message)
            case .other: break
            }
            emit("command-receipt id=\(message.inReplyTo ?? message.id)")
        case .error:
            let messageText: String
            if case .string(let value) = message.body["message"] {
                messageText = value
            } else {
                messageText = "Command was refused."
            }
            switch resolveCorrelation(of: message) {
            case .fileImport: jailedDrop.refuse(reason: messageText)
            case .terminalCreate, .other: break
            }
            lastCommandError = String(messageText.prefix(300))
            let errorCode: String
            if case .string(let value) = message.body["code"] {
                errorCode = value
            } else {
                errorCode = "E_COMMAND"
            }
            let approvalCorrelation: String
            if case .string(let approvalID) = message.body["approval_id"] {
                approvalCorrelation = " approval_id=\(approvalID)"
            } else {
                approvalCorrelation = ""
            }
            emit(
                "command-error id=\(message.inReplyTo ?? message.id) code=\(errorCode)"
                    + "\(approvalCorrelation) "
                    + "message=\(lastCommandError ?? "Command was refused.")"
            )
        case .streamDesynchronized:
            throw BirkinApplicationRuntimeError.replayRequired
        case .goodbye:
            throw BirkinApplicationRuntimeError.bridgeClosed
        default:
            break
        }
    }

    /// Remember which command a frame belongs to so its receipt can be typed.
    ///
    /// Correlation is bounded: entries are removed when the receipt or refusal
    /// arrives, and the whole table is dropped when the connection ends.
    private func correlate(_ request: NativeCommandRequest) {
        let kind = CorrelatedCommand(commandType: request.commandType)
        guard kind != .other else { return }
        correlatedCommands[request.frameID] = kind
    }

    private func resolveCorrelation(of message: NativeEnvelope) -> CorrelatedCommand {
        guard let reply = message.inReplyTo,
              let kind = correlatedCommands.removeValue(forKey: reply) else {
            return .other
        }
        return kind
    }

    private func installTerminalLease(from message: NativeEnvelope) {
        guard case .object(let result) = message.body["result"],
              case .string(let terminalID) = result["terminal_id"],
              case .string(let lease) = result["lease"] else { return }
        store.installTerminalLease(lease, forTerminal: terminalID)
        emit("terminal-lease-installed terminal=\(terminalID)")
    }

    private func applyImportResult(from message: NativeEnvelope) {
        guard case .object(let result) = message.body["result"] else {
            jailedDrop.refuse(reason: "Python returned no jailed import reference.")
            return
        }
        jailedDrop.applyCanonicalResult(result)
    }

    private func connectionLost(reason: String, generation: Int) async {
        guard started, generation == connectionGeneration else { return }
        correlatedCommands.removeAll()
        commandSubmitter = nil
        await transport.apply(.disconnect)
        emit("disconnected reason=\(reason)")
        await scheduleReconnect(reason: reason)
    }

    private func scheduleReconnect(reason: String) async {
        guard started, let scheduler else { return }
        connectionState = .connecting
        emit("reconnect-scheduled reason=\(reason)")
        await scheduler.disconnected()
    }

    /// Capture the launched app's compositor-backed window at the configured
    /// evidence path. Synthetic offscreen view rendering is never accepted.
    @discardableResult
    private func renderConfiguredEvidence(session _: NativeReadySession) async throws -> Bool {
        guard let screenshotPath else { return false }
        let target = presentationModel.target ?? .connection
        let generation = presentationModel.focus(target)
        try await presentationModel.waitUntilVisible(generation: generation)
        await Task.yield()
        let receipt = try captureEvidence(
            to: URL(fileURLWithPath: screenshotPath),
            focusTarget: target.evidenceName,
            focusGeneration: generation
        )
        return receipt.pixelWidth > 0 && receipt.pixelHeight > 0
    }

    /// Capture the launched app's owned window to an explicit destination.
    @discardableResult
    func renderEvidence(to url: URL, session _: NativeReadySession) throws -> Bool {
        let receipt = try captureEvidence(
            to: url,
            focusTarget: "window:birkin",
            focusGeneration: UInt64(max(0, store.latestAppliedCursor ?? 0))
        )
        return receipt.pixelWidth > 0 && receipt.pixelHeight > 0
    }

    func captureEvidence(
        to url: URL,
        focusTarget: String,
        focusGeneration: UInt64
    ) throws -> PackagedWindowCaptureReceipt {
        try windowCapture.capture(
            to: url,
            focusTarget: focusTarget,
            focusGeneration: focusGeneration
        )
    }

    func waitForEvidenceWindow() async throws {
        try await windowCapture.waitForOwnedWindow()
    }

    private func emit(_ message: String) {
        emitEvent(message)
    }

    nonisolated public static func standardEvent(_ message: String) {
        try? FileHandle.standardOutput.write(
            contentsOf: standardEventData(message)
        )
    }

    nonisolated static func standardEventData(_ message: String) -> Data {
        Data(
            "BIRKIN_APP_EVENT \(JourneyEvidenceRedactor.redact(message))\n".utf8
        )
    }

    nonisolated static func ownershipCorrelationDigest(_ token: String) -> String {
        SHA256.hash(data: Data(token.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
    }
}

/// A submitted command whose receipt carries state only this connection may
/// hold. Everything else is `.other`: its receipt needs no client action.
enum CorrelatedCommand: Equatable {
    case terminalCreate
    case fileImport
    case other

    init(commandType: String) {
        switch commandType {
        case "terminal.create": self = .terminalCreate
        case "file.import": self = .fileImport
        default: self = .other
        }
    }
}

private enum BirkinApplicationRuntimeError: Error {
    case replayRequired
    case bridgeClosed
}

/// The application's single runtime and its optional scripted QA journey.
///
/// The window starts the journey only after SwiftUI mounts the real shell.
@MainActor
enum BirkinApplicationHost {
    static let journey = PackagedJourneyConfiguration.discovered()
    /// Exists only for a QA run. A production launch keeps no journey log at
    /// all, so it cannot accumulate one line of it.
    static let journeyEvents: JourneyEventLog? =
        journey == nil ? nil : JourneyEventLog()
    static let runtime: BirkinApplicationRuntime = {
        // Captured once: a production launch has no log, so it never even
        // schedules the work that would append to one.
        let events = journeyEvents
        return BirkinApplicationRuntime(emit: { message in
            BirkinApplicationRuntime.standardEvent(message)
            guard let events else { return }
            Task { @MainActor in events.record(message) }
        })
    }()
}

/// Runs the app-owned bridge lifecycle across the real application lifecycle.
@MainActor
private final class BirkinApplicationDelegate: NSObject, NSApplicationDelegate {
    func applicationWillTerminate(_ notification: Notification) {
        BirkinApplicationHost.runtime.stop()
    }

    func applicationShouldTerminateAfterLastWindowClosed(
        _ sender: NSApplication
    ) -> Bool {
        true
    }
}

private struct BirkinRootView: View {
    @ObservedObject private var runtime = BirkinApplicationHost.runtime

    var body: some View {
        NativeShellView(
            store: runtime.store,
            connectionState: runtime.connectionState,
            commandError: runtime.lastCommandError,
            diagnosticsAction: runtime.showDiagnostics,
            mutationAction: runtime.submit,
            templateCommandAction: runtime.submit,
            productSurfaceAction: runtime.submit,
            voiceInputAction: runtime.beginVoiceInput,
            evidenceSpecimens: BirkinApplicationHost.journey == nil
                ? [] : PackagedWindowCapture.cjkSpecimens,
            jailedDrop: runtime.jailedDrop,
            presentationModel: runtime.presentationModel
        )
        .frame(minWidth: 960, minHeight: 640)
        .task {
            NSApplication.shared.activate(ignoringOtherApps: true)
            await runtime.start()
            guard let journey = BirkinApplicationHost.journey,
                  let events = BirkinApplicationHost.journeyEvents else {
                return
            }
            await PackagedJourneyRunner(
                configuration: journey,
                runtime: runtime,
                events: events
            ).run()
        }
    }
}

@main
struct BirkinNativeApplication: App {
    @NSApplicationDelegateAdaptor(BirkinApplicationDelegate.self) private var delegate

    var body: some Scene {
        WindowGroup(BirkinApplicationConfiguration.windowTitle) {
            BirkinRootView()
        }
        .defaultSize(width: 1280, height: 800)
    }
}
