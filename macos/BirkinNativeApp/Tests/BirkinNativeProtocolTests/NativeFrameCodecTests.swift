import Foundation
import Testing

@testable import BirkinNativeProtocol

/// Mirrors the framing refusals asserted in
/// `tests/test_native_protocol_codec.py`.
@Suite("Bounded frame codec")
struct NativeFrameCodecTests {
    private func refusal(frame: Data) -> NativeProtocolError.Code? {
        let error = #expect(throws: NativeProtocolError.self) {
            _ = try NativeEnvelope.decode(frame: frame)
        }
        return error?.code
    }

    @Test("a frame declaring more than the byte bound is refused before its body")
    func oversizedDeclaredLength() {
        let frame = TestFrame.header(declaring: NativeProtocol.maxFrameBytes + 1)

        #expect(refusal(frame: frame) == .frameTooLarge)
    }

    @Test("a frame shorter than its four-byte header is refused")
    func incompleteHeader() {
        #expect(refusal(frame: Data([0x00, 0x00, 0x00])) == .frameIncomplete)
    }

    @Test("a frame whose body is shorter than declared is refused")
    func truncatedBody() {
        var frame = TestFrame.header(declaring: 3)
        frame.append(Data("{}".utf8))

        #expect(refusal(frame: frame) == .frameIncomplete)
    }

    @Test("a truncated golden frame is refused")
    func truncatedGoldenFrame() throws {
        let vector = try GoldenVectors.named("hello")

        let frame = vector.frame.prefix(vector.frameByteCount - 1)

        #expect(refusal(frame: Data(frame)) == .frameIncomplete)
    }

    @Test("a frame carrying more bytes than declared is refused")
    func trailingData() throws {
        let vector = try GoldenVectors.named("hello")
        var frame = vector.frame
        frame.append(0x20)

        #expect(refusal(frame: frame) == .frameTrailingData)
    }

    @Test("a frame body that is not UTF-8 is refused")
    func invalidUTF8() {
        var frame = TestFrame.header(declaring: 1)
        frame.append(0xFF)

        #expect(refusal(frame: frame) == .invalidUTF8)
    }
}
