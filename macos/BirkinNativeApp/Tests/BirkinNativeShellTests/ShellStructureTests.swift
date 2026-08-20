import AppKit
import SwiftUI
import Testing

@testable import BirkinNativeProtocol
@testable import BirkinNativeShell

@Suite("Adaptive native shell hierarchy")
struct ShellStructureTests {
    @Test("shell exposes the complete three-column hierarchy without invented data")
    func completeHierarchy() throws {
        let store = NativeProjectionStore()
        let empty = ShellStructure(store: store)

        #expect(empty.columns.map(\.id) == [.navigation, .primary, .context])
        #expect(empty.columns.flatMap(\.sections).map(\.id) == ShellSectionID.allCases)
        #expect(empty.columns.flatMap(\.sections).allSatisfy {
            $0.state == .empty("Waiting for the canonical projection.")
        })

        try store.apply(snapshot: snapshot())
        let projected = ShellStructure(store: store)
        let conversation = projected.columns
            .flatMap(\.sections)
            .first { $0.id == .conversation }
        #expect(conversation?.state == .content(itemCount: 1))
        #expect(projected.columns.flatMap(\.sections).contains {
            $0.state == .unavailable("Not advertised by the Python projection.")
        })
    }

    @MainActor
    @Test("three-column shell renders fixed-size PNG evidence")
    func rendersShellEvidence() throws {
        let store = NativeProjectionStore()
        let now = Date(timeIntervalSince1970: 1_787_238_000)
        let session = NativeReadySession(
            instanceID: "instance-1",
            serverVersion: "1.0",
            sessionCapability: "token",
            capabilityExpiresAt: now.addingTimeInterval(60),
            capabilityHardExpiresAt: now.addingTimeInterval(120)
        )
        let view = NativeShellView(
            store: store,
            connectionState: .ready(session),
            now: now
        )
        .frame(width: 1_200, height: 760)
        let renderer = ImageRenderer(content: view)
        renderer.scale = 1
        guard let image = renderer.nsImage,
              let tiff = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let png = bitmap.representation(using: .png, properties: [:])
        else {
            Issue.record("ImageRenderer did not produce shell PNG data")
            return
        }
        let output = evidenceDirectory().appendingPathComponent("shell-three-column-empty.png")
        try FileManager.default.createDirectory(
            at: output.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try png.write(to: output, options: .atomic)
        #expect(png.count > 10_000)
    }

    private func snapshot() -> NativeEnvelope {
        NativeEnvelope(kind: .snapshot, id: "snapshot-1", body: [
            "protocol_version": .int(1),
            "session_id": .string("session-1"),
            "cursor": .int(1),
            "panels": .array([
                .object(["key": .string("sessions_history"), "items": .array([])]),
                .object(["key": .string("approvals"), "items": .array([])]),
                .object(["key": .string("activity_logs"), "items": .array([])]),
                .object(["key": .string("computer_use"), "items": .array([])]),
            ]),
            "conversation": .array([.object(["id": .string("event-1")])]),
            "composer": .object([
                "can_send": .bool(true),
                "can_interrupt": .bool(false),
                "can_resume": .bool(false),
            ]),
            "status": .object(["connection": .string("connected")]),
            "working_memory": .object([
                "revision": .int(0),
                "goal": .null,
                "fields": .object([
                    "corrections": .array([]), "constraints": .array([]),
                    "decisions": .array([]), "incomplete": .array([]),
                    "evidence": .array([]), "next_actions": .array([]),
                ]),
                "files_evidence": .array([]),
            ]),
            "instance_id": .string("instance-1"),
            "reset_reason": .string("initial"),
        ])
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
}
