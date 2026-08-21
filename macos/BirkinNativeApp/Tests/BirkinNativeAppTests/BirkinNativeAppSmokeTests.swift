import Testing

@testable import BirkinNativeApp
import BirkinNativeProtocol

@Suite("Packaged application smoke contract")
struct BirkinNativeAppSmokeTests {
    @Test("release identity and initial window are configured")
    func releaseIdentity() {
        #expect(BirkinApplicationConfiguration.bundleIdentifier == "com.birkin.native")
        #expect(BirkinApplicationConfiguration.version == BirkinVersion.package)
        #expect(BirkinApplicationConfiguration.build == "1")
        #expect(BirkinApplicationConfiguration.windowTitle == "Birkin")
    }
}
