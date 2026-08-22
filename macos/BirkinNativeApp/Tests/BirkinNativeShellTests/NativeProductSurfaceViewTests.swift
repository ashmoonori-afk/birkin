import AppKit
import BirkinNativeProtocol
import SwiftUI
import XCTest
@testable import BirkinNativeShell

@MainActor
final class NativeProductSurfaceViewTests: XCTestCase {
    func testGrantAndOfficeFactoriesCarryCurrentWorkflowIdentity() throws {
        let store = NativeProjectionStore()
        try store.apply(surface: envelope("computer_use", payload: [
            "status": .object(["permission_prompted": .bool(false)]),
            "consent": .object([
                "grant_id": .string("cu_grant_fixture_123456"),
                "state": .string("proposed"), "one_shot": .bool(true),
                "application_ref": .string("app:fixture"), "window_ref": .string("window:fixture"),
            ]),
            "receipts": .array([]),
        ]))
        let session = NativeReadySession(
            instanceID: "instance-1", serverVersion: "1.0.0", currentSessionID: "session-1",
            sessionCapability: "capability", supportedCommands: []
        )
        let consent = try XCTUnwrap(ComputerUsePresentation(store: store))
        let answer = try XCTUnwrap(ComputerUseCommandFactory.answer(
            decision: "approve", presentation: consent, store: store, session: session
        ))
        XCTAssertEqual(answer.commandType, "computer.answer")
        XCTAssertEqual(answer.payload["grant_id"], .string("cu_grant_fixture_123456"))

        let form = OfficeFormState(
            format: "docx", outputName: "notes.docx",
            content: ["paragraphs": .array([.string("Notes")])]
        )
        let create = try XCTUnwrap(OfficeCommandFactory.create(form: form, store: store, session: session))
        XCTAssertEqual(create.commandType, "office.create")
        XCTAssertEqual(create.payload["output_name"], .string("notes.docx"))
    }

    func testBrowserToolbarStatusAndFrameRenderAgainstRealLocalPage() throws {
        let page = try LocalPage()
        defer { page.close() }
        let data = try Data(contentsOf: page.url)
        XCTAssertTrue(String(decoding: data, as: UTF8.self).contains("BIRKIN PHASE 10 LOCAL PAGE"))

        let store = NativeProjectionStore()
        try store.apply(surface: envelope("browser_aside", payload: [
            "profile": .object(["kind": .string("private_workspace"), "generation": .int(4)]),
            "runtime": .object(["live": .bool(true)]),
            "control": .object(["owner_kind": .string("human"), "epoch": .int(1), "expires_at": .string("2026-08-20T12:01:00+00:00")]),
            "navigation": .object([
                "display_url": .string(page.url.absoluteString), "loading": .bool(false),
                "history": .object([
                    "can_go_back": .bool(true), "can_go_forward": .bool(false),
                    "entries": .array([.string(page.url.absoluteString)]), "index": .int(0),
                ]),
            ]),
            "frame": .object([
                "ref": .string("frame:4:1"), "revision": .int(1),
                "digest": .string("hmac-sha256:local-page"),
                "media_type": .string("image/png"), "max_bytes": .int(8388608),
            ]),
            "refusal": .null,
        ]))
        let presentation = try XCTUnwrap(BrowserAsidePresentation(store: store))
        let view = BrowserAsideView(
            presentation: presentation, navigate: { _ in }, back: {}, forward: {}, reload: {}, close: {}
        )
            .frame(width: 620, height: 260).padding().background(Color(nsColor: .windowBackgroundColor))
        try snapshot(view, named: "browser-aside-local-page.png")
    }

    func testOfficeNewOpenAndRefusalRender() throws {
        let store = NativeProjectionStore()
        try store.apply(surface: envelope("office", payload: [
            "inventory": .array([.object(["format": .string("docx")]), .object(["format": .string("pdf")])]),
            "form": .object([
                "format": .string("docx"), "output_name": .string("phase10.docx"),
                "content": .object(["paragraphs": .array([.string("Phase 10")])]),
            ]),
            "selected_artifact_id": .string("document:phase10"),
            "documents": .array([.object([
                "artifact_id": .string("document:phase10"),
                "active_content": .array([]),
                "provenance": .object(["content_hash": .string("sha256:phase10")]),
            ])]),
            "receipts": .array([.object(["operation": .string("document_create")]), .object(["operation": .string("document_open")])]),
            "refusal": .object(["code": .string("path_refused")]),
        ]))
        let presentation = try XCTUnwrap(OfficePresentation(store: store))
        let view = OfficeView(
            presentation: presentation, canCreate: true, canOpen: true,
            createForm: { _ in }, open: {}, select: { _ in }
        ).frame(width: 620, height: 260).padding().background(Color(nsColor: .windowBackgroundColor))
        try snapshot(view, named: "office-new-open-refusal.png")
    }

    func testConsentCountdownActionsProduceEvidence() throws {
        let store = NativeProjectionStore()
        try store.apply(surface: envelope("computer_use", payload: [
            "status": .object([
                "permission_prompted": .bool(false),
                "permissions": .object([
                    "accessibility": .string("granted"), "screen_capture": .string("denied"),
                ]),
                "backend": .object(["state": .string("available")]),
                "binding": .object(["state": .string("bound")]),
            ]),
            "consent": .object([
                "grant_id": .string("cu_grant_fixture_123456"),
                "state": .string("proposed"), "one_shot": .bool(true),
                "application_ref": .string("app:fixture"), "window_ref": .string("window:fixture"),
                "expires_at": .string("2026-08-20T12:01:00Z"),
            ]),
            "receipts": .array([]),
        ]))
        let now = ISO8601DateFormatter().date(from: "2026-08-20T12:00:42Z")!
        let presentation = try XCTUnwrap(ComputerUsePresentation(store: store, now: now))
        var actions: [String] = []
        let view = ComputerUseStatusView(
            presentation: presentation, canDecide: true,
            approve: { actions.append("approve-once") },
            reject: { actions.append("reject") }
        )
        XCTAssertEqual(presentation.countdownText, "18s")
        XCTAssertEqual(presentation.grantID, "cu_grant_fixture_123456")
        XCTAssertEqual(presentation.screenRecordingStatus, "denied")
        view.approve()
        view.reject()
        actions.append("countdown=18s")
        actions.append("binding=app:fixture/window:fixture")
        try evidenceURL("computer-use-consent-action.log").writeText(actions.joined(separator: "\n") + "\n")
        try snapshot(view.frame(width: 620, height: 220).padding(), named: "computer-use-consent.png")
    }

    private func envelope(_ surface: String, payload: NativeJSONObject) -> NativeEnvelope {
        NativeEnvelope(
            kind: .surfaceSnapshot, id: "surface-\(surface)",
            body: ["surface": .string(surface), "revision": .int(1), "payload": .object(payload)]
        )
    }

    private func snapshot<V: View>(_ view: V, named: String) throws {
        let hosting = NSHostingView(rootView: view)
        hosting.frame = NSRect(x: 0, y: 0, width: 680, height: 300)
        hosting.layoutSubtreeIfNeeded()
        guard let bitmap = hosting.bitmapImageRepForCachingDisplay(in: hosting.bounds) else {
            return XCTFail("could not allocate screenshot")
        }
        hosting.cacheDisplay(in: hosting.bounds, to: bitmap)
        guard let png = bitmap.representation(using: .png, properties: [:]) else {
            return XCTFail("could not encode screenshot")
        }
        try png.write(to: evidenceURL(named), options: .atomic)
    }

    private func evidenceURL(_ name: String) throws -> URL {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { root.deleteLastPathComponent() }
        let directory = root.appendingPathComponent(".omo/evidence/native-shell", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory.appendingPathComponent(name)
    }
}

private final class LocalPage {
    let process: Process
    let url: URL

    init() throws {
        process = Process()
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = ["-c", """
import http.server
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body=b'<!doctype html><h1>BIRKIN PHASE 10 LOCAL PAGE</h1>'
        self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *args): pass
s=http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
print(s.server_port, flush=True)
s.serve_forever()
"""]
        try process.run()
        let handle = pipe.fileHandleForReading
        var ready = Data()
        while !ready.contains(0x0a) {
            let byte = handle.readData(ofLength: 1)
            guard !byte.isEmpty else { throw CocoaError(.fileReadUnknown) }
            ready.append(byte)
        }
        guard let port = Int(String(decoding: ready, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)),
              let value = URL(string: "http://127.0.0.1:\(port)/") else {
            throw CocoaError(.fileReadCorruptFile)
        }
        url = value
    }

    func close() {
        if process.isRunning { process.terminate(); process.waitUntilExit() }
    }
}

private extension URL {
    func writeText(_ value: String) throws {
        try Data(value.utf8).write(to: self, options: .atomic)
    }
}
