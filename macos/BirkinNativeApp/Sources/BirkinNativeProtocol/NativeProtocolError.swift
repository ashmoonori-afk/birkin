/// A bounded protocol refusal carrying the same public code as the Python
/// bridge raises in `birkin/native/protocol.py`.
public struct NativeProtocolError: Error, Equatable, Sendable, CustomStringConvertible {
    /// Stable refusal codes shared with the Python codec.
    public enum Code: String, Equatable, Sendable, CaseIterable {
        case envelopeKeys = "E_ENVELOPE_KEYS"
        case protocolName = "E_PROTOCOL"
        case protocolVersion = "E_PROTOCOL_VERSION"
        case kind = "E_KIND"
        case identifier = "E_IDENTIFIER"
        case json = "E_JSON"
        case jsonDepth = "E_JSON_DEPTH"
        case duplicateKey = "E_DUPLICATE_KEY"
        case nonfiniteNumber = "E_NONFINITE_NUMBER"
        case invalidUTF8 = "E_INVALID_UTF8"
        case frameTooLarge = "E_FRAME_TOO_LARGE"
        case frameIncomplete = "E_FRAME_INCOMPLETE"
        case frameTrailingData = "E_FRAME_TRAILING_DATA"
    }

    public let code: Code
    public let message: String

    public init(_ code: Code, _ message: String) {
        self.code = code
        self.message = message
    }

    public var description: String { "\(code.rawValue): \(message)" }
}
