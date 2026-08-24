import Testing

@testable import BirkinNativeProtocol

@Suite("Native protocol constants")
struct NativeProtocolConstantsTests {
    @Test("wire constants match birkin/native/protocol.py")
    func wireConstants() {
        #expect(NativeProtocol.name == "birkin-local-1")
        #expect(NativeProtocol.version == 1)
        #expect(NativeProtocol.maxFrameBytes == 262_144)
        #expect(NativeProtocol.maxJSONDepth == 12)
    }

    @Test("every registered message kind is known")
    func registeredKinds() {
        #expect(NativeProtocol.kinds.count == 15)
        #expect(NativeProtocol.kinds.contains("capability.renewed"))
        #expect(NativeProtocol.kinds.contains("stream.desynchronized"))
        #expect(!NativeProtocol.kinds.contains("invented"))
    }
}
