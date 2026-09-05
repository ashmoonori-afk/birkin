import AppKit
import Foundation
import SwiftUI
import Testing

@testable import BirkinNativeProtocol
@testable import BirkinNativeShell

@Suite("Menu bar navigation-only authority")
struct MenuBarNavigationTests {
    @Test("connection session and approval items carry destinations but no decisions")
    func navigationOnly() {
        let model = DesktopMenuModel(
            connection: .ready(NativeReadySession(
                instanceID: "instance-1", serverVersion: "1.0",
                sessionCapability: "token"
            )),
            sessionID: "session-7", pendingApprovalCount: 2
        )

        #expect(model.connectionTitle == "연결됨")
        #expect(model.items.map(\.destination) == [
            .connection, .session(id: "session-7"), .approvals,
        ])
        #expect(model.items.allSatisfy { $0.kind == .navigate })
        #expect(model.items.map(\.title) == [
            "연결: 연결됨", "업무: session-7", "승인 요청 2건",
        ])
    }

    @MainActor
    @Test("menu renders screenshot and invokes navigation destination only")
    func screenshotEvidence() throws {
        let model = DesktopMenuModel(
            connection: .disconnected,
            sessionID: "session-7", pendingApprovalCount: 1
        )
        var routes: [DesktopMenuDestination] = []
        let view = DesktopMenuView(model: model, navigate: { routes.append($0) })
            .padding().frame(width: 300, height: 180, alignment: .topLeading)
        let renderer = ImageRenderer(content: view)
        let image = try #require(renderer.nsImage)
        let bitmap = try #require(image.tiffRepresentation.flatMap(NSBitmapImageRep.init))
        let png = try #require(bitmap.representation(using: .png, properties: [:]))
        let output = evidenceDirectory().appendingPathComponent("desktop-menu.png")
        try FileManager.default.createDirectory(
            at: output.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        try png.write(to: output, options: .atomic)
        #expect(png.count > 2_000)
        #expect(routes.isEmpty)
    }

    private func evidenceDirectory() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent(".omo/evidence/native-shell")
    }
}
