import AppKit
import BirkinNativeProtocol
import SwiftUI
import Testing
@testable import BirkinNativeShell

@Suite("Phase 12 visual references")
struct Phase12VisualReferenceTests {
    @MainActor
    @Test("empty shell and every active journey surface render fixed references")
    func renderReferences() throws {
        let now = Date(timeIntervalSince1970: 1_787_238_000)
        let session = NativeReadySession(
            instanceID: "instance-12", serverVersion: "1.0", sessionCapability: "token",
            capabilityExpiresAt: now.addingTimeInterval(60),
            capabilityHardExpiresAt: now.addingTimeInterval(120)
        )
        try snapshot(
            NativeShellView(store: NativeProjectionStore(), connectionState: .ready(session), now: now),
            named: "empty-shell.png", size: NSSize(width: 1_536, height: 1_024)
        )

        let store = NativeProjectionStore()
        try store.apply(snapshot: activeSnapshot())
        try store.apply(surface: surface("browser_aside", payload: browserPayload))
        try store.apply(surface: surface("computer_use", payload: computerUsePayload))
        try store.apply(surface: surface("office", payload: officePayload))

        try snapshot(
            NativeShellView(
                store: store, connectionState: .ready(session), now: now,
                initialColumn: .navigation
            ),
            named: "session-list.png", size: NSSize(width: 860, height: 900)
        )
        let projection = try #require(store.projection)
        try snapshot(
            MessageStreamView(projection: projection),
            named: "conversation-stream.png", size: NSSize(width: 680, height: 420)
        )
        try snapshot(
            WorkingMemoryView(
                presentation: WorkingMemoryPresentation(projection: projection.workingMemory),
                clearPresentation: WorkingMemoryClearPresentation(sessionID: projection.sessionID),
                canClear: true
            ),
            named: "working-memory.png", size: NSSize(width: 680, height: 520)
        )
        try snapshot(
            TerminalView(
                terminal: try #require(projection.terminals.first), canMutate: true,
                sendInput: { _ in }, interrupt: {}, close: {}
            ),
            named: "terminal.png", size: NSSize(width: 680, height: 420)
        )
        let approvalItem = try #require(projection.panels
            .first { $0.key == "approvals" }?.items.first)
        try snapshot(
            ApprovalCardView(
                presentation: try #require(ApprovalCardPresentation(item: approvalItem)),
                canDecide: true, approve: {}, reject: {}
            ),
            named: "approvals.png", size: NSSize(width: 680, height: 300)
        )
        try snapshot(
            BrowserAsideView(
                presentation: try #require(BrowserAsidePresentation(store: store)),
                navigate: { _ in }
            ),
            named: "browser.png", size: NSSize(width: 680, height: 320)
        )
        try snapshot(
            ComputerUseStatusView(
                presentation: try #require(ComputerUsePresentation(store: store, now: now)),
                canDecide: true
            ),
            named: "computer-use-consent.png", size: NSSize(width: 680, height: 300)
        )
        try snapshot(
            OfficeView(
                presentation: try #require(OfficePresentation(store: store)),
                canCreate: true, canOpen: true
            ),
            named: "office.png", size: NSSize(width: 680, height: 260)
        )
    }

    @MainActor
    private func snapshot<V: View>(_ view: V, named: String, size: NSSize) throws {
        let renderer = ImageRenderer(content:
            view.padding(20).frame(width: size.width, height: size.height)
                .background(Color(nsColor: .windowBackgroundColor))
                .environment(\.colorScheme, .dark)
                .environment(
                    \.shellVisualSettings,
                    ShellVisualSettings(snapshotRendering: true)
                )
        )
        renderer.scale = 1
        let image = try #require(renderer.nsImage)
        #expect(image.size == size)
        let tiff = try #require(image.tiffRepresentation)
        let bitmap = try #require(NSBitmapImageRep(data: tiff))
        let png = try #require(bitmap.representation(using: .png, properties: [:]))
        #expect(png.count > 4_000)
        try png.write(to: evidenceURL(named), options: .atomic)
    }

    private func activeSnapshot() -> NativeEnvelope {
        NativeEnvelope(kind: .snapshot, id: "phase12-active", body: [
            "protocol_version": .int(1), "session_id": .string("session-12"), "cursor": .int(12),
            "panels": .array([
                .object(["key": .string("sessions_history"), "items": .array([
                    .object(["id": .string("session-12"), "name": .string("접근성 검토 세션"), "status": .string("running")]),
                ])]),
                .object(["key": .string("approvals"), "items": .array([.object([
                    "kind": .string("approval"), "id": .string("approval-12"),
                    "risk": .string("high"), "summary": .string("Apply sealed file change"),
                    "description": .string("Writes the reviewed diff inside the workspace jail."),
                    "category": .string("file_write"), "sealed": .bool(true), "decided": .bool(false),
                ])])]),
                .object(["key": .string("activity_logs"), "items": .array([.object([
                    "id": .string("receipt-12"), "kind": .string("receipt"),
                    "summary": .string("Terminal command completed"),
                ])])]),
            ]),
            "conversation": .array([
                .object(["id": .string("message-1"), "kind": .string("user_message"), "text": .string("Review the accessibility evidence.")]),
                .object(["id": .string("message-2"), "kind": .string("assistant_stream"), "text": .string("Inspecting the native hierarchy and active surfaces…")]),
            ]),
            "composer": .object(["can_send": .bool(true), "can_interrupt": .bool(true), "can_resume": .bool(false)]),
            "status": .object(["connection": .string("connected")]),
            "terminals": .array([.object([
                "terminal_id": .string("terminal-12"), "cwd": .string("/workspace"),
                "screen": .string("$ swift test\nAll tests passed\n"), "output_sequence": .int(2),
                "state": .string("running"), "exit_status": .null, "columns": .int(80),
                "rows": .int(24), "lease": .string("lease-12"), "read_only": .bool(false),
            ])]),
            "approval_policy": .object([
                "requested": .object(["auto_approve": .null]),
                "effective": .object(["auto_approve": .array([])]), "pending_requests": .array([]),
            ]),
            "working_memory": .object([
                "revision": .int(4),
                "goal": .object([
                    "slug": .string("accessible-native-journeys"),
                    "objective": .string("Ship accessible native journeys"),
                    "tokens_used": .int(18), "status": .string("active"),
                ]),
                "fields": .object([
                    "corrections": .array([]), "constraints": .array([.string("No pointer required")]),
                    "decisions": .array([.string("Use canonical Python authority")]),
                    "incomplete": .array([]), "evidence": .array([.string("VoiceOver seam is green")]),
                    "next_actions": .array([.string("Review screenshots")]),
                ]),
                "files_evidence": .array([.object(["summary": .string("Sources/BirkinNativeShell")])]),
            ]),
            "instance_id": .string("instance-12"), "reset_reason": .string("initial"),
        ])
    }

    private var browserPayload: NativeJSONObject { [
        "profile": .object(["kind": .string("private_workspace"), "generation": .int(12)]),
        "runtime": .object(["live": .bool(true)]),
        "control": .object(["owner_kind": .string("human"), "epoch": .int(1), "expires_at": .string("2026-08-20T12:01:00Z")]),
        "navigation": .object(["display_url": .string("http://127.0.0.1:8080/evidence")]),
        "frame": .object(["ref": .string("frame:12"), "revision": .int(3)]), "refusal": .null,
    ] }

    private var computerUsePayload: NativeJSONObject { [
        "status": .object(["permission_prompted": .bool(false)]),
        "consent": .object([
            "state": .string("proposed"), "one_shot": .bool(true),
            "application_ref": .string("app:fixture"), "window_ref": .string("window:fixture"),
            "expires_at": .string("2026-08-20T12:01:00Z"),
        ]), "receipts": .array([]),
    ] }

    private var officePayload: NativeJSONObject { [
        "inventory": .array([.object(["format": .string("docx")]), .object(["format": .string("pdf")])]),
        "documents": .array([.object(["artifact_id": .string("document:phase12")])]),
        "receipts": .array([.object(["operation": .string("document_create")])]), "refusal": .null,
    ] }

    private func surface(_ name: String, payload: NativeJSONObject) -> NativeEnvelope {
        NativeEnvelope(kind: .surfaceSnapshot, id: "surface-\(name)", body: [
            "surface": .string(name), "revision": .int(1), "payload": .object(payload),
        ])
    }

    private func evidenceURL(_ name: String) throws -> URL {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { root.deleteLastPathComponent() }
        let directory = root.appendingPathComponent(".omo/evidence/native-shell/phase12", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory.appendingPathComponent(name)
    }
}
