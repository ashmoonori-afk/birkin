import Foundation
import Testing

@testable import BirkinNativeProtocol

/// Cross-language parity: every vector in the fixture was produced by
/// `birkin.native.protocol.encode_frame`, so Swift must both understand those
/// bytes and reproduce them exactly.
@Suite("Golden vector parity with the Python codec")
struct NativeGoldenVectorParityTests {
    @Test("every registered message kind has a golden vector")
    func everyKindIsCovered() throws {
        let kinds = Set(try GoldenVectors.all().map(\.kind))

        #expect(kinds == NativeProtocol.kinds)
    }

    @Test("Swift decodes every Python-encoded vector")
    func decodesEveryVector() throws {
        let vectors = try GoldenVectors.all()

        #expect(!vectors.isEmpty)
        for vector in vectors {
            let envelope = try NativeFrameCodec.decode(frame: vector.frame)

            #expect(envelope.kind.rawValue == vector.kind, "vector \(vector.name)")
            #expect(envelope.protocolName == NativeProtocol.name, "vector \(vector.name)")
            #expect(vector.frame.count == vector.frameByteCount, "vector \(vector.name)")
        }
    }

    @Test("Swift re-encodes every vector to byte-identical frames")
    func reencodesEveryVectorIdentically() throws {
        for vector in try GoldenVectors.all() {
            let envelope = try NativeFrameCodec.decode(frame: vector.frame)

            let reencoded = try NativeFrameCodec.encode(envelope)

            #expect(
                Array(reencoded) == Array(vector.frame),
                "vector \(vector.name) re-encoded to \(reencoded.count) bytes, expected \(vector.frameByteCount)"
            )
        }
    }

    @Test("a re-encoded frame decodes back to an equal envelope")
    func reencodedFramesRoundTrip() throws {
        for vector in try GoldenVectors.all() {
            let envelope = try NativeFrameCodec.decode(frame: vector.frame)

            let roundTripped = try NativeFrameCodec.decode(
                frame: try NativeFrameCodec.encode(envelope)
            )

            #expect(roundTripped == envelope, "vector \(vector.name)")
        }
    }
}
