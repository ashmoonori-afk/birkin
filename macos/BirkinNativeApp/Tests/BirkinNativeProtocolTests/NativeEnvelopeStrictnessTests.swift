import Foundation
import Testing

@testable import BirkinNativeProtocol

/// Mirrors the refusals asserted in `tests/test_native_protocol_codec.py`.
@Suite("Envelope strictness parity with the Python codec")
struct NativeEnvelopeStrictnessTests {
    private func decode(json: String) throws -> NativeEnvelope {
        try NativeEnvelope.decode(frame: TestFrame.make(json: json))
    }

    private func refusal(json: String) -> NativeProtocolError.Code? {
        let error = #expect(throws: NativeProtocolError.self) {
            _ = try decode(json: json)
        }
        return error?.code
    }

    @Test("an envelope with an extra key is refused")
    func extraKey() {
        let json = """
            {"protocol":"birkin-local-1","protocol_version":1,"kind":"ping",\
            "id":"extra","in_reply_to":null,"body":{},"extra":"forbidden"}
            """

        #expect(refusal(json: json) == .envelopeKeys)
    }

    @Test("an envelope missing a key is refused")
    func missingKey() {
        let json = """
            {"protocol":"birkin-local-1","protocol_version":1,"kind":"ping",\
            "id":"missing","body":{}}
            """

        #expect(refusal(json: json) == .envelopeKeys)
    }

    @Test("a foreign protocol name is refused")
    func foreignProtocol() {
        let json = """
            {"protocol":"not-birkin","protocol_version":1,"kind":"ping",\
            "id":"foreign","in_reply_to":null,"body":{}}
            """

        #expect(refusal(json: json) == .protocolName)
    }

    @Test("a boolean protocol_version is refused")
    func booleanProtocolVersion() {
        let json = """
            {"protocol":"birkin-local-1","protocol_version":true,"kind":"ping",\
            "id":"boolean","in_reply_to":null,"body":{}}
            """

        #expect(refusal(json: json) == .protocolVersion)
    }

    @Test("an unsupported protocol_version is refused")
    func unsupportedProtocolVersion() {
        let json = """
            {"protocol":"birkin-local-1","protocol_version":2,"kind":"ping",\
            "id":"future","in_reply_to":null,"body":{}}
            """

        #expect(refusal(json: json) == .protocolVersion)
    }

    @Test("an unknown kind is refused")
    func unknownKind() {
        let json = """
            {"protocol":"birkin-local-1","protocol_version":1,"kind":"invented",\
            "id":"unknown","in_reply_to":null,"body":{}}
            """

        #expect(refusal(json: json) == .kind)
    }

    @Test("an identifier outside the bounded alphabet is refused")
    func invalidIdentifier() {
        let json = """
            {"protocol":"birkin-local-1","protocol_version":1,"kind":"ping",\
            "id":"has space","in_reply_to":null,"body":{}}
            """

        #expect(refusal(json: json) == .identifier)
    }

    @Test("an in_reply_to outside the bounded alphabet is refused")
    func invalidReplyIdentifier() {
        let json = """
            {"protocol":"birkin-local-1","protocol_version":1,"kind":"pong",\
            "id":"reply","in_reply_to":"bad id","body":{}}
            """

        #expect(refusal(json: json) == .identifier)
    }

    @Test("a non-object body is refused")
    func nonObjectBody() {
        let json = """
            {"protocol":"birkin-local-1","protocol_version":1,"kind":"ping",\
            "id":"body","in_reply_to":null,"body":[]}
            """

        #expect(refusal(json: json) == .json)
    }

    @Test("a duplicate JSON key is refused")
    func duplicateKey() {
        let json = """
            {"protocol":"birkin-local-1","protocol_version":1,"kind":"ping",\
            "kind":"pong","id":"duplicate-key","in_reply_to":null,"body":{}}
            """

        #expect(refusal(json: json) == .duplicateKey)
    }

    @Test(
        "a non-finite JSON number is refused",
        arguments: ["NaN", "Infinity", "-Infinity"]
    )
    func nonfiniteNumber(constant: String) {
        let json = """
            {"protocol":"birkin-local-1","protocol_version":1,"kind":"ping",\
            "id":"nonfinite","in_reply_to":null,"body":{"value":\(constant)}}
            """

        #expect(refusal(json: json) == .nonfiniteNumber)
    }

    @Test("a body at maximum depth is accepted")
    func maximumDepthAccepted() throws {
        let json = TestFrame.nestedBodyJSON(levels: NativeProtocol.maxJSONDepth - 1)

        let envelope = try decode(json: json)

        #expect(envelope.kind == .ping)
        #expect(envelope.body["child"] != nil)
    }

    @Test("a body beyond maximum depth is refused")
    func beyondMaximumDepthRefused() {
        let json = TestFrame.nestedBodyJSON(levels: NativeProtocol.maxJSONDepth)

        #expect(refusal(json: json) == .jsonDepth)
    }

    @Test("every registered kind decodes into a typed kind")
    func registeredKinds() throws {
        for kind in NativeProtocol.kinds.sorted() {
            let json = """
                {"protocol":"birkin-local-1","protocol_version":1,\
                "kind":"\(kind)","id":"kinds","in_reply_to":null,"body":{}}
                """

            #expect(try decode(json: json).kind.rawValue == kind)
        }
    }
}

enum TestFrame {
    /// Length-prefix arbitrary JSON text exactly the way the Python codec does.
    static func make(json: String) -> Data {
        let body = Data(json.utf8)
        var frame = header(declaring: body.count)
        frame.append(body)
        return frame
    }

    /// A bare four-byte big-endian length prefix.
    static func header(declaring length: Int) -> Data {
        Data(withUnsafeBytes(of: UInt32(length).bigEndian) { Array($0) })
    }

    /// A `ping` envelope whose body nests `levels` child objects.
    static func nestedBodyJSON(levels: Int) -> String {
        var body = "{}"
        for _ in 0..<levels {
            body = "{\"child\":\(body)}"
        }
        return """
            {"protocol":"birkin-local-1","protocol_version":1,"kind":"ping",\
            "id":"nested","in_reply_to":null,"body":\(body)}
            """
    }
}
