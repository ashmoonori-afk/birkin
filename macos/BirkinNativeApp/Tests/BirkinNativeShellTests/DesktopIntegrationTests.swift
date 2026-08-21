import AppKit
import Foundation
import SwiftUI
import Testing

@testable import BirkinNativeProtocol
@testable import BirkinNativeShell

@Suite("Desktop drag and drop")
@MainActor
struct DesktopDropTests {
    @Test("drop moves through hover and accept before canonical imported chip")
    func canonicalImportFlow() {
        let session = readySession(commands: ["file.import"])
        let model = JailedDropModel()
        var requests: [NativeCommandRequest] = []
        let external = URL(fileURLWithPath: "/Users/example/Desktop/plan.txt")

        model.setHovering(true)
        #expect(model.state == .hovering)
        let accepted = model.accept(
            urls: [external], availability: liveAvailability(session),
            expectedCursor: 4, session: session, submit: { requests.append($0) }
        )

        #expect(accepted)
        #expect(model.state == .importing(displayName: "plan.txt"))
        #expect(requests.count == 1)
        #expect(requests[0].commandType == "file.import")
        #expect(requests[0].payload.string("source_path") == external.path)

        model.applyCanonicalResult([
            "reference": .object([
                "kind": .string("workspace_import"),
                "import_id": .string("import-1"),
                "display_name": .string("plan.txt"),
                "jail_name": .string("import-1.txt"),
                "sha256": .string(String(repeating: "a", count: 64)),
                "byte_count": .int(42),
            ]),
            "receipt": .object(["copied": .bool(true)]),
        ])
        #expect(model.state == .imported)
        #expect(model.reference?.displayName == "plan.txt")
        #expect(model.reference?.importID == "import-1")
        #expect(model.reference?.composerToken == "[[workspace-import:import-1]]")
        #expect(model.reference?.composerToken.contains("/Users/example") == false)
    }

    @Test("imported reference chip renders screenshot evidence")
    func screenshotEvidence() throws {
        let model = JailedDropModel()
        model.applyCanonicalResult([
            "reference": .object([
                "kind": .string("workspace_import"),
                "import_id": .string("import-evidence"),
                "display_name": .string("quarterly-plan.txt"),
                "jail_name": .string("import-evidence.txt"),
                "sha256": .string(String(repeating: "b", count: 64)),
                "byte_count": .int(128),
            ]),
            "receipt": .object(["copied": .bool(true)]),
        ])
        let view = JailedDropZone(model: model, acceptURLs: { _ in })
            .padding().frame(width: 420, height: 120)
        let renderer = ImageRenderer(content: view)
        let image = try #require(renderer.nsImage)
        let tiff = try #require(image.tiffRepresentation)
        let bitmap = try #require(NSBitmapImageRep(data: tiff))
        let png = try #require(bitmap.representation(using: .png, properties: [:]))
        let output = evidenceDirectory().appendingPathComponent("jailed-import-chip.png")
        try FileManager.default.createDirectory(
            at: output.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        try png.write(to: output, options: .atomic)
        #expect(png.count > 2_000)
    }

    @Test("the attachment picker is keyboard reachable through jailed import")
    func attachmentPickerInventory() throws {
        // Given: the complete native accessibility and keyboard inventories.
        let node = try #require(ShellAccessibilityInventory.nodes.first {
            $0.id == "composer.attach"
        })

        // When / Then: the picker is a pressable composer action with its own
        // shortcut, while file.import remains Python's eventual authority.
        #expect(node.role == .button)
        #expect(node.actions == ["press"])
        #expect(ShellKeyboardModel.commands.contains {
            $0.shortcut == "cmd+shift+o" && $0.action == "composer.attach"
        })
    }

    @Test("non-file and unavailable drops are refused without transport")
    func refusal() {
        let session = readySession(commands: ["file.import"])
        let model = JailedDropModel()
        var requests: [NativeCommandRequest] = []
        #expect(!model.accept(
            urls: [URL(string: "https://example.com/a")!],
            availability: liveAvailability(session), expectedCursor: 0,
            session: session, submit: { requests.append($0) }
        ))
        #expect(model.state == .refused(reason: "Drop a local regular file."))
        #expect(!model.accept(
            urls: [URL(fileURLWithPath: "/tmp/a")],
            availability: MutationAvailability(state: .disconnected), expectedCursor: 0,
            session: session, submit: { requests.append($0) }
        ))
        #expect(requests.isEmpty)
    }
}

private func evidenceDirectory() -> URL {
    URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .appendingPathComponent(".omo/evidence/native-shell")
}

private func readySession(commands: Set<String>) -> NativeReadySession {
    NativeReadySession(
        instanceID: "instance-1", serverVersion: "1.0",
        sessionCapability: "token",
        capabilityExpiresAt: Date(timeIntervalSince1970: 2_000),
        capabilityHardExpiresAt: Date(timeIntervalSince1970: 3_000),
        supportedCommands: commands
    )
}

private func liveAvailability(_ session: NativeReadySession) -> MutationAvailability {
    MutationAvailability(state: .ready(session), now: Date(timeIntervalSince1970: 1_000))
}

private extension NativeJSONObject {
    func string(_ key: String) -> String? {
        guard case .string(let value) = self[key] else { return nil }
        return value
    }
}
