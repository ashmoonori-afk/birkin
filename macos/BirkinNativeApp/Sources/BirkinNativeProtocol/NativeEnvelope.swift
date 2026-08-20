import Foundation

/// One validated native-protocol envelope.
///
/// Validation follows `NativeEnvelope.parse` in `birkin/native/protocol.py`
/// key for key and refusal for refusal: the key set must match exactly, the
/// protocol name and version are pinned, the kind must be registered, both
/// identifiers are bounded, and the body is a depth-bounded JSON object.
public struct NativeEnvelope: Equatable, Sendable {
    /// The exact envelope key set; anything else is a refusal.
    static let envelopeKeys: Set<String> = [
        "protocol", "protocol_version", "kind", "id", "in_reply_to", "body",
    ]

    public let protocolName: String
    public let protocolVersion: Int
    public let kind: NativeMessageKind
    public let id: String
    public let inReplyTo: String?
    public let body: NativeJSONObject

    public init(
        protocolName: String = NativeProtocol.name,
        protocolVersion: Int = NativeProtocol.version,
        kind: NativeMessageKind,
        id: String,
        inReplyTo: String? = nil,
        body: NativeJSONObject = NativeJSONObject()
    ) {
        self.protocolName = protocolName
        self.protocolVersion = protocolVersion
        self.kind = kind
        self.id = id
        self.inReplyTo = inReplyTo
        self.body = body
    }

    /// Decode the envelope carried by one complete frame.
    public static func decode(frame: Data) throws(NativeProtocolError) -> NativeEnvelope {
        try validate(json: try parseJSON(body: NativeFrameCodec.body(of: frame)))
    }

    /// Decode the UTF-8 JSON body of a frame, before envelope validation.
    static func parseJSON(body: Data) throws(NativeProtocolError) -> NativeJSONValue {
        guard let text = String(data: body, encoding: .utf8) else {
            throw NativeProtocolError(.invalidUTF8, "frame is not UTF-8")
        }
        return try NativeJSONParser.parse(utf8: Array(text.utf8))
    }

    /// Validate one parsed JSON document as an envelope.
    static func validate(json: NativeJSONValue) throws(NativeProtocolError) -> NativeEnvelope {
        guard case .object(let mapping) = json else {
            throw NativeProtocolError(.json, "envelope must be a JSON object")
        }
        guard Set(mapping.keys) == envelopeKeys, mapping.count == envelopeKeys.count else {
            throw NativeProtocolError(
                .envelopeKeys,
                "native envelope keys do not match the protocol"
            )
        }
        guard case .string(let name) = mapping["protocol"], name == NativeProtocol.name else {
            throw NativeProtocolError(.protocolName, "unsupported native protocol")
        }
        guard case .int(let version) = mapping["protocol_version"] else {
            throw NativeProtocolError(.protocolVersion, "protocol_version must be an integer")
        }
        guard version == NativeProtocol.version else {
            throw NativeProtocolError(
                .protocolVersion,
                "unsupported protocol_version \(version)"
            )
        }
        guard case .string(let rawKind) = mapping["kind"],
            let kind = NativeMessageKind(rawValue: rawKind)
        else {
            throw NativeProtocolError(.kind, "unsupported native message kind")
        }
        let id = try identifier(mapping["id"], label: "id")
        var reply: String?
        if mapping["in_reply_to"] != .null {
            reply = try identifier(mapping["in_reply_to"], label: "in_reply_to")
        }
        guard case .object(let body) = mapping["body"] else {
            throw NativeProtocolError(.json, "body must be a JSON object")
        }
        try validateObject(body, depth: 1)
        return NativeEnvelope(
            protocolName: name,
            protocolVersion: version,
            kind: kind,
            id: id,
            inReplyTo: reply,
            body: body
        )
    }

    /// The envelope as the canonical key-ordered JSON object Python emits.
    var canonicalJSON: NativeJSONObject {
        var object = NativeJSONObject()
        // `append` only fails on duplicate keys, and these six are distinct.
        try? object.append(key: "protocol", value: .string(protocolName))
        try? object.append(key: "protocol_version", value: .int(protocolVersion))
        try? object.append(key: "kind", value: .string(kind.rawValue))
        try? object.append(key: "id", value: .string(id))
        try? object.append(
            key: "in_reply_to",
            value: inReplyTo.map(NativeJSONValue.string) ?? .null
        )
        try? object.append(key: "body", value: .object(body))
        return object
    }

    private static func identifier(
        _ value: NativeJSONValue?,
        label: String
    ) throws(NativeProtocolError) -> String {
        guard case .string(let text) = value, isIdentifier(text) else {
            throw NativeProtocolError(.identifier, "\(label) must be a bounded identifier")
        }
        return text
    }

    private static func isIdentifier(_ text: String) -> Bool {
        let scalars = text.unicodeScalars
        guard scalars.count >= 1, scalars.count <= 128 else { return false }
        return scalars.allSatisfy { scalar in
            switch scalar {
            case "A"..."Z", "a"..."z", "0"..."9": return true
            case ".", "_", ":", "-": return true
            default: return false
            }
        }
    }

    /// Enforce `MAX_JSON_DEPTH` with the same counting the Python codec uses:
    /// the body itself is depth 1 and its members are depth 2.
    static func validateObject(
        _ object: NativeJSONObject,
        depth: Int
    ) throws(NativeProtocolError) {
        guard depth <= NativeProtocol.maxJSONDepth else {
            throw NativeProtocolError(.jsonDepth, "JSON exceeds maximum depth")
        }
        for pair in object.pairs {
            try validateValue(pair.value, depth: depth + 1)
        }
    }

    static func validateValue(
        _ value: NativeJSONValue,
        depth: Int
    ) throws(NativeProtocolError) {
        guard depth <= NativeProtocol.maxJSONDepth else {
            throw NativeProtocolError(.jsonDepth, "JSON exceeds maximum depth")
        }
        switch value {
        case .double(let number) where !number.isFinite:
            throw NativeProtocolError(.nonfiniteNumber, "body contains a non-finite number")
        case .array(let values):
            for element in values {
                try validateValue(element, depth: depth + 1)
            }
        case .object(let object):
            try validateObject(object, depth: depth)
        default: return
        }
    }
}
