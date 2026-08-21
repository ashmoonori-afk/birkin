import Foundation
import Testing

@testable import BirkinNativeApp
import BirkinNativeProtocol
import BirkinNativeShell

@Suite("Truthful browser controls")
struct BrowserControlTests {
    private static let session = NativeReadySession(
        instanceID: "instance-1",
        serverVersion: BirkinVersion.package,
        currentSessionID: "session-1",
        sessionCapability: "capability-token",
        supportedCommands: ["browser.navigate"]
    )

    private static func store(displayURL: String) throws -> NativeProjectionStore {
        let store = NativeProjectionStore()
        try store.apply(surface: NativeEnvelope(
            kind: .surfaceSnapshot,
            id: "surface-browser",
            body: [
                "surface": .string("browser_aside"),
                "revision": .int(3),
                "payload": .object([
                    "profile": .object([
                        "kind": .string("private_workspace"), "generation": .int(7),
                    ]),
                    "runtime": .object([
                        "live": .bool(true), "engine": .string("chromium"),
                        "revision": .int(5),
                    ]),
                    "control": .object([
                        "owner_kind": .string("human"), "epoch": .int(1),
                        "expires_at": .null,
                    ]),
                    "navigation": .object([
                        "display_url": .string(displayURL),
                    ]),
                    "frame": .object([
                        "ref": .string("frame:7:5"), "revision": .int(5),
                    ]),
                    "refusal": .null,
                ]),
            ]
        ))
        return store
    }

    @MainActor
    @Test("navigation carries the requested address, not the current page")
    func navigationCarriesTheRequestedAddress() throws {
        let store = try Self.store(displayURL: "http://127.0.0.1:8123/current")
        let request = try #require(BrowserCommandFactory.navigate(
            to: "http://127.0.0.1:8123/next", store: store, session: Self.session
        ))

        #expect(request.commandType == "browser.navigate")
        #expect(request.payload["url"] == .string("http://127.0.0.1:8123/next"))
        #expect(request.payload["generation"] == .int(7))
        #expect(request.payload["revision"] == .int(5))
    }

    @MainActor
    @Test("a blank or whitespace address never becomes a command")
    func blankAddressIsRefused() throws {
        let store = try Self.store(displayURL: "http://127.0.0.1:8123/current")

        #expect(BrowserCommandFactory.navigate(to: "", store: store, session: Self.session) == nil)
        #expect(BrowserCommandFactory.navigate(to: "   ", store: store, session: Self.session) == nil)
    }

    @MainActor
    @Test("navigation is impossible without a live browser surface identity")
    func missingSurfaceProducesNoCommand() throws {
        let empty = NativeProjectionStore()

        #expect(BrowserCommandFactory.navigate(
            to: "http://127.0.0.1:8123/next", store: empty, session: Self.session
        ) == nil)
    }

    @MainActor
    @Test("the shell advertises only browser commands Python registers")
    func onlyRegisteredBrowserCommandsAreOffered() {
        let offered = Set(ProductSurfaceControl.browserCommandTypes)

        #expect(offered == ["browser.navigate"])
    }
}
