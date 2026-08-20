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
            "navigation": .object(["display_url": .string("http://127.0.0.1:8123/")]),
            "frame": .object(["ref": .string("frame:7:2"), "revision": .int(2)]),
            "refusal": .null,
        ]))
        try store.apply(surface: surface("computer_use", revision: 1, payload: [
            "status": .object(["permission_prompted": .bool(false)]),
            "consent": .object([
                "state": .string("approved"), "one_shot": .bool(true),
                "expires_at": .string("2026-08-20T12:01:00+00:00"),
                "application_ref": .string("app:7"), "window_ref": .string("window:9"),
            ]),
            "receipts": .array([]),
        ]))
        try store.apply(surface: surface("office", revision: 1, payload: [
            "inventory": .array([.object(["format": .string("docx")])]),
            "documents": .array([]), "receipts": .array([]), "refusal": .null,
        ]))

        XCTAssertEqual(BrowserAsidePresentation(store: store)?.profileGeneration, 7)
        XCTAssertEqual(BrowserAsidePresentation(store: store)?.frameRevision, 2)
        let consent = ComputerUsePresentation(store: store, now: date("2026-08-20T12:00:42+00:00"))
        XCTAssertEqual(consent?.countdownText, "18s")
        XCTAssertEqual(consent?.applicationRef, "app:7")
        XCTAssertEqual(OfficePresentation(store: store)?.formats, ["docx"])
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
