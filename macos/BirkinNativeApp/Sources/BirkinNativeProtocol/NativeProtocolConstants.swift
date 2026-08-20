/// Wire constants for Birkin's local native protocol.
///
/// These mirror `birkin/native/protocol.py`, which is the authoritative
/// definition. Every value here is cross-checked against a fixture produced by
/// the real Python codec in `NativeProtocolConstantsTests`.
public enum NativeProtocol {
    /// The only protocol name accepted on the wire.
    public static let name = "birkin-local-1"

    /// The only envelope `protocol_version` accepted on the wire.
    public static let version = 1

    /// Maximum encoded body size of one frame, excluding the length prefix.
    public static let maxFrameBytes = 262_144

    /// Maximum nesting depth allowed inside an envelope body.
    public static let maxJSONDepth = 12

    /// Every message kind the protocol registers.
    public static let kinds: Set<String> = Set(
        NativeMessageKind.allCases.map(\.rawValue)
    )
}
