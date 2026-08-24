import AppKit
import SwiftUI
import Testing

@testable import BirkinNativeProtocol
@testable import BirkinNativeShell

@Suite("Connection status rendered evidence")
struct ConnectionRenderingTests {
    @MainActor
    @Test("all connection phases render deterministic PNG evidence")
    func rendersEveryPhase() throws {
        let session = NativeReadySession(
            instanceID: "instance-1",
            serverVersion: "1.0",
            sessionCapability: "live-token"
        )
        let states: [(String, ConnectionPresentation)] = [
            ("disconnected", .init(state: .disconnected)),
            ("connecting", .init(state: .connecting)),
            ("handshaking", .init(state: .negotiating(.uds))),
            ("ready-uds", .init(state: .ready(session))),
            ("fallback-connecting", .init(state: .fallback(.connecting(reason: "socket missing")))),
            ("fallback-handshaking", .init(state: .fallback(.negotiating))),
            ("fallback-ready", .init(state: .fallback(.ready(session)))),
            ("reconnecting", .reconnecting(attempt: 3, retryAfter: 4)),
            ("replaying", .init(state: .replaying(session))),
            ("failed", .init(state: .failed(reason: "bridge stopped"))),
        ]
        let directory = evidenceDirectory()
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )

        for (name, presentation) in states {
            let view = ConnectionStatusPill(presentation: presentation)
                .frame(width: 720, height: 92)
                .padding(12)
                .background(Color(nsColor: .windowBackgroundColor))
            let renderer = ImageRenderer(content: view)
            renderer.scale = 2
            guard let image = renderer.nsImage,
                  let tiff = image.tiffRepresentation,
                  let bitmap = NSBitmapImageRep(data: tiff),
                  let png = bitmap.representation(using: .png, properties: [:])
            else {
                Issue.record("ImageRenderer did not produce PNG data for \(name)")
                continue
            }
            let output = directory.appendingPathComponent("connection-\(name).png")
            try png.write(to: output, options: .atomic)
            #expect(png.count > 1_000)
        }
    }

    private func evidenceDirectory() -> URL {
        let testFile = URL(fileURLWithPath: #filePath)
        let repository = testFile
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        return repository.appendingPathComponent(".omo/evidence/native-shell")
    }
}
