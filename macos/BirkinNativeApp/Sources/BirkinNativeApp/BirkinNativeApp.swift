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
private final class BirkinApplicationModel: ObservableObject {
    let store = NativeProjectionStore()
    @Published private(set) var connectionState: NativeConnectionState = .disconnected
    private var started = false

    func connectFromEnvironment() async {
        guard !started else { return }
        started = true
        let environment = ProcessInfo.processInfo.environment
        guard let socketPath = environment[BirkinApplicationConfiguration.socketEnvironmentKey]
        else {
            emit("disconnected reason=no-endpoint")
            return
        }
        connectionState = .connecting
        do {
            let initial = try await Task.detached {
                let transport = NativeTransportActor()
                return try await transport.loadInitialProjectionUDS(
                    socketPath: socketPath,
                    hello: NativeHello(
                        client: "birkin-macos",
                        clientVersion: BirkinApplicationConfiguration.version,
                        clientBuild: BirkinApplicationConfiguration.build,
                        surface: "macos",
                        viewID: "main"
                    ),
                    sessionID: "session-1"
                )
            }.value
            try store.apply(snapshot: initial.snapshot)
            connectionState = .ready(initial.session)
            if let path = environment[BirkinApplicationConfiguration.screenshotEnvironmentKey] {
                try renderEvidence(to: URL(fileURLWithPath: path), session: initial.session)
            }
            emit(
                "connected transport=uds session=session-1 cursor=\(store.latestAppliedCursor ?? -1) "
                    + "conversation=\(store.projection?.conversation.count ?? 0)"
            )
        } catch {
            connectionState = .failed(reason: String(describing: error))
            emit("failed reason=\(String(describing: error))")
        }
    }

    private func renderEvidence(to url: URL, session: NativeReadySession) throws {
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
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try png.write(to: url, options: .atomic)
    }

    private func emit(_ message: String) {
        let line = Data("BIRKIN_APP_EVENT \(message)\n".utf8)
        try? FileHandle.standardOutput.write(contentsOf: line)
    }
}

private struct BirkinRootView: View {
    @StateObject private var model = BirkinApplicationModel()

    var body: some View {
        NativeShellView(store: model.store, connectionState: model.connectionState)
            .frame(minWidth: 960, minHeight: 640)
            .task { await model.connectFromEnvironment() }
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
