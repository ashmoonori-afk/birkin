import Testing

@testable import BirkinNativeProtocol

@Suite("Envelope decoding of Python golden vectors")
struct NativeEnvelopeVectorTests {
    @Test("the Python hello frame decodes into typed envelope values")
    func helloVector() throws {
        let vector = try GoldenVectors.named("hello")

        let envelope = try NativeEnvelope.decode(frame: vector.frame)

        #expect(envelope.protocolName == NativeProtocol.name)
        #expect(envelope.protocolVersion == NativeProtocol.version)
        #expect(envelope.kind == .hello)
        #expect(envelope.id == "hello-1")
        #expect(envelope.inReplyTo == nil)
        #expect(envelope.body["client"] == .string("birkin-macos"))
        #expect(envelope.body["client_version"] == .string("0.1.0"))
        #expect(envelope.body["supported_protocol_versions"] == .array([.int(1)]))
        #expect(envelope.body["absent"] == nil)
    }

    @Test("the Python ready frame decodes into typed envelope values")
    func readyVector() throws {
        let vector = try GoldenVectors.named("ready")

        let envelope = try NativeEnvelope.decode(frame: vector.frame)

        #expect(envelope.kind == .ready)
        #expect(envelope.id == "ready-1")
        #expect(envelope.inReplyTo == "hello-1")
        #expect(envelope.body["server"] == .string("birkin"))
        #expect(envelope.body["instance_id"] == .string("birkin-local"))
        #expect(
            envelope.body["capability"]
                == .object([
                    "token": .string("cap-token-1"),
                    "expires_in_seconds": .int(900),
                ])
        )
        #expect(
            envelope.body["surfaces"]
                == .array([.string("session"), .string("conversation")])
        )
    }

    @Test("the fixture reports the Python protocol constants")
    func fixtureConstants() throws {
        let constants = try GoldenVectors.protocolConstants()

        #expect(constants["name"] as? String == NativeProtocol.name)
        #expect(constants["version"] as? Int == NativeProtocol.version)
        #expect(constants["max_frame_bytes"] as? Int == NativeProtocol.maxFrameBytes)
        #expect(constants["max_json_depth"] as? Int == NativeProtocol.maxJSONDepth)
    }
}
