import AppKit
import BirkinNativeProtocol
import BirkinNativeShell
import SwiftUI

public enum BirkinApplicationConfiguration {
    public static let bundleIdentifier = "com.birkin.native"
    public static let version = "0.4.242"
    public static let build = "1"
    public static let windowTitle = "Birkin"
    public static let socketEnvironmentKey = "BIRKIN_NATIVE_SOCKET"
    public static let screenshotEnvironmentKey = "BIRKIN_NATIVE_SCREENSHOT"
}

@MainActor
public final class BirkinApplicationRuntime: ObservableObject {
    public let store = NativeProjectionStore()
    @Published public private(set) var connectionState: NativeConnectionState = .disconnected
    @Published public private(set) var lastCommandError: String?

    private let socketPath: String?
    private let screenshotPath: String?
    private let reconnectClock: any NativeReconnectClock
    private let randomUnit: NativeReconnectScheduler.RandomUnit
    private let emitEvent: @Sendable (String) -> Void
    private let transport = NativeTransportActor()
    private var scheduler: NativeReconnectScheduler?
    private var listener: Task<Void, Never>?
    private var commandSubmitter: (@Sendable (NativeCommandRequest) throws -> Void)?
    private var started = false
    private var connectionGeneration = 0

    public init(
        socketPath: String? = ProcessInfo.processInfo.environment[
            BirkinApplicationConfiguration.socketEnvironmentKey
        ],
        screenshotPath: String? = ProcessInfo.processInfo.environment[
            BirkinApplicationConfiguration.screenshotEnvironmentKey
        ],
        reconnectClock: any NativeReconnectClock = NativeContinuousReconnectClock(),
        randomUnit: @escaping NativeReconnectScheduler.RandomUnit = {
            Double.random(in: 0...1)
        },
        emit: @escaping @Sendable (String) -> Void = BirkinApplicationRuntime.standardEvent
    ) {
        self.socketPath = socketPath
        self.screenshotPath = screenshotPath
        self.reconnectClock = reconnectClock
        self.randomUnit = randomUnit
        self.emitEvent = emit
    }

    public func start() async {
        guard !started else { return }
        started = true
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

    public func stop() {
        started = false
        connectionGeneration += 1
        listener?.cancel()
        listener = nil
        commandSubmitter = nil
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
            try renderConfiguredEvidence(session: subscription.session)
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
        guard let commandSubmitter else {
            lastCommandError = "Command transport is not connected."
            return
        }
        lastCommandError = nil
        Task.detached { [weak self] in
            do {
                try commandSubmitter(request)
            } catch {
                await MainActor.run {
                    self?.lastCommandError = String(describing: error).prefix(300).description
                }
            }
        }
    }

    public func showDiagnostics() {
        emit("diagnostics state=\(String(describing: connectionState))")
    }

    public func submit(_ control: ShellMutationControl) {
        guard let session = readySession else {
            lastCommandError = "Command transport is not ready."
            return
        }
        let commandType: String
        let payload: NativeJSONObject
        switch control {
        case .newSession:
            commandType = "session.create"
            payload = ["session_id": .string(UUID().uuidString.lowercased())]
        case .sendMessage:
            commandType = "chat.send"
            payload = ["text": .string("")]
        case .newTerminal:
            commandType = "terminal.create"
            payload = ["actor_kind": .string("native_human"), "cwd": .string(FileManager.default.currentDirectoryPath)]
        case .terminalInput:
            commandType = "terminal.input"
            payload = [:]
        case .terminalInterrupt:
            commandType = "terminal.signal"
            payload = [:]
        case .terminalClose:
            commandType = "terminal.close"
            payload = [:]
        }
        submit(request(commandType: commandType, payload: payload, session: session, viewID: "shell-control"))
    }

    public func submit(_ control: ProductSurfaceControl) {
        guard let session = readySession else {
            lastCommandError = "Command transport is not ready."
            return
        }
        switch control {
        case .browserBack, .browserForward, .browserReload, .browserNavigate:
            guard let surface = store.surface(named: "browser_aside"),
                  case .object(let profile) = surface.payload["profile"],
                  case .int(let generation) = profile["generation"],
                  case .object(let runtime) = surface.payload["runtime"],
                  case .int(let revision) = runtime["revision"],
                  case .object(let navigation) = surface.payload["navigation"],
                  case .string(let url) = navigation["display_url"] else {
                lastCommandError = "Browser surface identity is unavailable."
                return
            }
            submit(request(
                commandType: "browser.navigate",
                payload: ["url": .string(url), "generation": .int(generation), "revision": .int(revision)],
                session: session, viewID: "browser-aside"
            ))
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
                    "content": .object(["title": .string("Birkin document"), "paragraphs": .array([])]),
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
            emit("projection-event type=\(eventType) cursor=\(store.latestAppliedCursor ?? -1)")
        case .snapshot:
            try store.apply(snapshot: message)
        case .surfaceEvent, .surfaceSnapshot:
            try store.apply(surface: message)
            if case .string(let surfaceName) = message.body["surface"] {
                emit("surface-applied name=\(surfaceName)")
            }
            if let session = readySession {
                try renderConfiguredEvidence(session: session)
            }
            if case .replayRequired = store.status {
                throw BirkinApplicationRuntimeError.replayRequired
            }
        case .capabilityRenewed:
            try await transport.acceptCapabilityRenewal(message)
            connectionState = await transport.state
        case .receipt:
            lastCommandError = nil
            emit("command-receipt id=\(message.inReplyTo ?? message.id)")
        case .error:
            let messageText: String
            if case .string(let value) = message.body["message"] {
                messageText = value
            } else {
                messageText = "Command was refused."
            }
            lastCommandError = String(messageText.prefix(300))
            emit("command-error message=\(lastCommandError ?? "Command was refused.")")
        case .streamDesynchronized:
            throw BirkinApplicationRuntimeError.replayRequired
        case .goodbye:
            throw BirkinApplicationRuntimeError.bridgeClosed
        default:
            break
        }
    }

    private func connectionLost(reason: String, generation: Int) async {
        guard started, generation == connectionGeneration else { return }
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

    private func renderConfiguredEvidence(session: NativeReadySession) throws {
        guard let screenshotPath else { return }
        let url = URL(fileURLWithPath: screenshotPath)
        let view = NativeShellView(store: store, connectionState: .ready(session))
            .frame(width: 1280, height: 800)
        let renderer = ImageRenderer(content: view)
        renderer.proposedSize = ProposedViewSize(width: 1280, height: 800)
        renderer.scale = 1
        guard let image = renderer.nsImage,
              let tiff = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let png = bitmap.representation(using: .png, properties: [:])
        else {
            throw CocoaError(.fileWriteUnknown)
        }
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        try png.write(to: url, options: .atomic)
    }

    private func emit(_ message: String) {
        emitEvent(message)
    }

    nonisolated public static func standardEvent(_ message: String) {
        let line = Data("BIRKIN_APP_EVENT \(message)\n".utf8)
        try? FileHandle.standardOutput.write(contentsOf: line)
    }
}

private enum BirkinApplicationRuntimeError: Error {
    case replayRequired
    case bridgeClosed
}

private struct BirkinRootView: View {
    @StateObject private var runtime = BirkinApplicationRuntime()

    var body: some View {
        NativeShellView(
            store: runtime.store,
            connectionState: runtime.connectionState,
            commandError: runtime.lastCommandError,
            diagnosticsAction: runtime.showDiagnostics,
            mutationAction: runtime.submit,
            templateCommandAction: runtime.submit,
            productSurfaceAction: runtime.submit,
            voiceInputAction: runtime.beginVoiceInput
        )
        .frame(minWidth: 960, minHeight: 640)
            .task { await runtime.start() }
    }
}

@main
struct BirkinNativeApplication: App {
    var body: some Scene {
        WindowGroup(BirkinApplicationConfiguration.windowTitle) {
            BirkinRootView()
        }
        .defaultSize(width: 1280, height: 800)
    }
}
