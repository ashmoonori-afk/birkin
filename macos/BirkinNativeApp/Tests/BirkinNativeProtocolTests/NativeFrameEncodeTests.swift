import Foundation
import Testing

@testable import BirkinNativeProtocol

@Suite("Frame encoding bounds")
struct NativeFrameEncodeTests {
    private func padded(_ length: Int) -> NativeEnvelope {
        NativeEnvelope(
            kind: .event,
            id: "bound",
            body: ["pad": .string(String(repeating: "a", count: length))]
        )
    }

    private func refusal(encoding envelope: NativeEnvelope) -> NativeProtocolError.Code? {
        let error = #expect(throws: NativeProtocolError.self) {
            _ = try NativeFrameCodec.encode(envelope)
        }
        return error?.code
    }

    @Test("an encoded frame declares its own body length")
    func lengthPrefix() throws {
        let frame = try NativeFrameCodec.encode(padded(16))

        var declared = 0
        for byte in frame.prefix(4) { declared = declared << 8 | Int(byte) }
        #expect(declared == frame.count - 4)
        #expect(try NativeFrameCodec.decode(frame: frame) == padded(16))
    }

    @Test("a body of exactly the byte bound is encoded and decoded")
    func exactlyAtBound() throws {
        let overhead = try NativeFrameCodec.encode(padded(0)).count - 4

        let frame = try NativeFrameCodec.encode(
            padded(NativeProtocol.maxFrameBytes - overhead)
        )

        #expect(frame.count - 4 == NativeProtocol.maxFrameBytes)
        #expect(try NativeFrameCodec.decode(frame: frame).kind == .event)
    }

    @Test("a body one byte past the bound is refused")
    func oneBytePastBound() throws {
        let overhead = try NativeFrameCodec.encode(padded(0)).count - 4

        let envelope = padded(NativeProtocol.maxFrameBytes - overhead + 1)

        #expect(refusal(encoding: envelope) == .frameTooLarge)
    }

    @Test("encoding revalidates a constructed envelope")
    func revalidatesConstructedEnvelope() {
        let envelope = NativeEnvelope(
            protocolName: "not-birkin",
            kind: .ping,
            id: "constructed"
        )

        #expect(refusal(encoding: envelope) == .protocolName)
    }

    @Test("encoding refuses an unbounded identifier")
    func refusesUnboundedIdentifier() {
        let envelope = NativeEnvelope(
            kind: .ping,
            id: String(repeating: "i", count: 129)
        )

        #expect(refusal(encoding: envelope) == .identifier)
    }

    @Test("encoding refuses a non-finite number")
    func refusesNonfiniteNumber() {
        let envelope = NativeEnvelope(
            kind: .ping,
            id: "nonfinite",
            body: ["value": .double(.nan)]
        )

        #expect(refusal(encoding: envelope) == .nonfiniteNumber)
    }

    @Test("encoding refuses a body beyond the depth bound")
    func refusesDeepBody() {
        var value = NativeJSONValue.object([:])
        for _ in 0..<NativeProtocol.maxJSONDepth {
            value = .object(["child": value])
        }
        guard case .object(let body) = value else { return }

        #expect(refusal(encoding: NativeEnvelope(kind: .ping, id: "deep", body: body))
            == .jsonDepth)
    }
}
