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

    private let socketPath: String?
    private let screenshotPath: String?
    private let reconnectClock: any NativeReconnectClock
    private let randomUnit: NativeReconnectScheduler.RandomUnit
    private let emitEvent: @Sendable (String) -> Void
    private let transport = NativeTransportActor()
    private var scheduler: NativeReconnectScheduler?
    private var listener: Task<Void, Never>?
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
                sessionID: "session-1",
                replaying: replaying
            )
            if subscription.replaying {
                connectionState = .replaying(subscription.session)
                emit("replaying session=session-1 after_cursor=0")
            }
            try store.apply(snapshot: subscription.snapshot)
            if subscription.replaying {
                await transport.replayCompleted()
            }
            connectionState = await transport.state
            connectionGeneration += 1
            let generation = connectionGeneration
            listen(to: subscription.messages, generation: generation)
            if replaying {
                emit(
                    "replayed session=session-1 cursor=\(store.latestAppliedCursor ?? -1)"
                )
            } else {
                emit(
                    "connected transport=uds session=session-1 "
                        + "cursor=\(store.latestAppliedCursor ?? -1) "
                        + "conversation=\(store.projection?.conversation.count ?? 0)"
                )
                try renderConfiguredEvidence(session: subscription.session)
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

    private func apply(_ message: NativeEnvelope) async throws {
        switch message.kind {
        case .event:
            try store.apply(event: message)
        case .snapshot:
            try store.apply(snapshot: message)
        case .surfaceEvent, .surfaceSnapshot:
            try store.apply(surface: message)
        case .capabilityRenewed:
            try await transport.acceptCapabilityRenewal(message)
            connectionState = await transport.state
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
        NativeShellView(store: runtime.store, connectionState: runtime.connectionState)
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
