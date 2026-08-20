import Testing

@testable import BirkinNativeApp

@Suite("Packaged application smoke contract")
struct BirkinNativeAppSmokeTests {
    @Test("release identity and initial window are configured")
    func releaseIdentity() {
        #expect(BirkinApplicationConfiguration.bundleIdentifier == "com.birkin.native")
        #expect(BirkinApplicationConfiguration.version == "0.4.242")
        #expect(BirkinApplicationConfiguration.build == "1")
        #expect(BirkinApplicationConfiguration.windowTitle == "Birkin")
    }
}
