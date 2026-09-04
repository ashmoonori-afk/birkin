import XCTest
@testable import BirkinNativeProtocol

final class NativeProductSurfaceTests: XCTestCase {
    func testSurfaceGapDiscardsOnlySurfaceAndRequestsFullSnapshot() throws {
        let store = NativeProjectionStore()
        try store.apply(surface: surface("browser_aside", revision: 1, payload: [
            "profile": .object(["kind": .string("private_workspace"), "generation": .int(7)])
        ]))
        try store.apply(surface: surface("browser_aside", revision: 3, payload: [:], kind: .surfaceEvent))

        XCTAssertNil(store.surface(named: "browser_aside"))
        XCTAssertEqual(store.requestedSurfaceRevisions["browser_aside"], 0)
        XCTAssertEqual(store.status, .replayRequired(NativeReplayRequest(
            afterCursor: 0, knownInstanceID: nil, replay: true
        )))
    }

    func testTypedBrowserComputerUseAndOfficePresentations() throws {
        let store = NativeProjectionStore()
        try store.apply(surface: surface("browser_aside", revision: 1, payload: [
            "profile": .object(["kind": .string("private_workspace"), "generation": .int(7)]),
            "runtime": .object(["live": .bool(true)]),
            "control": .object(["owner_kind": .string("human"), "epoch": .int(2), "expires_at": .string("2026-08-20T12:01:00+00:00")]),
            "navigation": .object([
                "display_url": .string("http://127.0.0.1:8123/"), "loading": .bool(false),
                "history": .object([
                    "can_go_back": .bool(true), "can_go_forward": .bool(false),
                    "entries": .array([.string("http://127.0.0.1:8123/")]), "index": .int(0),
                ]),
            ]),
            "frame": .object([
                "ref": .string("frame:7:2"), "revision": .int(2),
                "digest": .string("hmac-sha256:frame"), "media_type": .string("image/png"),
                "max_bytes": .int(8388608),
            ]),
            "refusal": .null,
        ]))
        try store.apply(surface: surface("computer_use", revision: 1, payload: [
            "status": .object([
                "permission_prompted": .bool(false),
                "permissions": .object([
                    "accessibility": .string("granted"), "screen_capture": .string("granted"),
                ]),
                "backend": .object(["state": .string("available")]),
                "binding": .object(["state": .string("bound")]),
                "guidance": .array([.object([
                    "capability": .string("capture_ax"),
                    "permission": .string("accessibility"),
                    "responsible_process": .string("org.example.BirkinQA"),
                    "settings_path": .string("settings-path://accessibility"),
                ])]),
            ]),
            "consent": .object([
                "grant_id": .string("cu_grant_fixture_123456"),
                "state": .string("approved"), "one_shot": .bool(true),
                "expires_at": .string("2026-08-20T12:01:00+00:00"),
                "application_ref": .string("app:7"), "window_ref": .string("window:9"),
            ]),
            "receipts": .array([]),
        ]))
        try store.apply(surface: surface("office", revision: 1, payload: [
            "inventory": .array([.object(["format": .string("docx")])]),
            "form": .object([
                "format": .string("docx"), "output_name": .string("notes.docx"),
                "content": .object(["paragraphs": .array([.string("Notes")])]),
            ]),
            "selected_artifact_id": .string("artifact:1"),
            "documents": .array([]), "receipts": .array([]), "refusal": .null,
        ]))

        XCTAssertEqual(BrowserAsidePresentation(store: store)?.profileGeneration, 7)
        let browser = BrowserAsidePresentation(store: store)
        XCTAssertEqual(browser?.frameRevision, 2)
        XCTAssertEqual(browser?.frameDigest, "hmac-sha256:frame")
        XCTAssertEqual(browser?.canGoBack, true)
        XCTAssertEqual(browser?.isLoading, false)
        let consent = ComputerUsePresentation(store: store, now: date("2026-08-20T12:00:42+00:00"))
        XCTAssertEqual(consent?.countdownText, "18s")
        XCTAssertEqual(consent?.applicationRef, "app:7")
        XCTAssertEqual(consent?.grantID, "cu_grant_fixture_123456")
        XCTAssertEqual(consent?.accessibilityStatus, "granted")
        XCTAssertEqual(consent?.screenRecordingStatus, "granted")
        XCTAssertEqual(consent?.backendStatus, "available")
        XCTAssertEqual(consent?.permissionPrompted, false)
        XCTAssertEqual(consent?.guidance.map(\.id), ["capture_ax"])
        XCTAssertEqual(consent?.guidance.first?.permission, "accessibility")
        XCTAssertEqual(consent?.guidance.first?.responsibleProcess, "org.example.BirkinQA")
        XCTAssertFalse(consent?.guidance.first?.settingsPath.isEmpty ?? true)
        let office = OfficePresentation(store: store)
        XCTAssertEqual(office?.formats, ["docx"])
        XCTAssertEqual(office?.form.outputName, "notes.docx")
        XCTAssertEqual(office?.selectedArtifactID, "artifact:1")
    }

    private func surface(
        _ name: String, revision: Int, payload: NativeJSONObject,
        kind: NativeMessageKind = .surfaceSnapshot
    ) -> NativeEnvelope {
        NativeEnvelope(
            kind: kind, id: "surface-\(name)-\(revision)", inReplyTo: nil,
            body: ["surface": .string(name), "revision": .int(revision), "payload": .object(payload)]
        )
    }

    private func date(_ value: String) -> Date {
        ISO8601DateFormatter().date(from: value)!
    }
}
