import Foundation
import Testing

@testable import BirkinNativeApp
import BirkinNativeProtocol

@Suite("Packaged application smoke contract")
struct BirkinNativeAppSmokeTests {
    @Test("release identity and initial window are configured")
    func releaseIdentity() {
        #expect(BirkinApplicationConfiguration.bundleIdentifier == "com.birkin.native")
        #expect(BirkinApplicationConfiguration.version == BirkinVersion.packageVersion)
        #expect(BirkinApplicationConfiguration.build == "1")
        #expect(BirkinApplicationConfiguration.windowTitle == "Birkin")
    }

    @Test("QA journey requires an explicit HTTP Browser fixture")
    func journeyBrowserFixture() throws {
        let base = [
            PackagedJourneyConfiguration.enabledKey: "1",
            PackagedJourneyConfiguration.evidenceKey: "/tmp/evidence",
            PackagedJourneyConfiguration.workspaceKey: "/tmp/workspace",
        ]
        #expect(PackagedJourneyConfiguration.discovered(in: base) == nil)
        #expect(PackagedJourneyConfiguration.discovered(in: base.merging([
            PackagedJourneyConfiguration.browserURLKey: "file:///tmp/page.html",
        ], uniquingKeysWith: { _, value in value })) == nil)

        let configured = try #require(PackagedJourneyConfiguration.discovered(
            in: base.merging([
                PackagedJourneyConfiguration.browserURLKey:
                    "http://127.0.0.1:8123/packaged-journey",
            ], uniquingKeysWith: { _, value in value })
        ))
        #expect(configured.browserURL.absoluteString ==
            "http://127.0.0.1:8123/packaged-journey")
    }
}
