import Foundation

/// The length-prefixed frame layer of the native protocol.
///
/// The wire format is the one `encode_frame` in `birkin/native/protocol.py`
/// writes: a four-byte big-endian body length followed by exactly that many
/// bytes of compact UTF-8 JSON. Frames declaring more than
/// `NativeProtocol.maxFrameBytes` are refused before their body is read, and a
/// body that does not match its declared length is refused as truncated or as
/// carrying trailing data.
public enum NativeFrameCodec {
    /// Validate an envelope and encode it as one complete frame.
    public static func encode(
        _ envelope: NativeEnvelope
    ) throws(NativeProtocolError) -> Data {
        let canonical = envelope.canonicalJSON
        _ = try NativeEnvelope.validate(json: .object(canonical))
        let body = NativeJSONSerializer.encode(object: canonical)
        guard body.count <= NativeProtocol.maxFrameBytes else {
            throw NativeProtocolError(.frameTooLarge, "native frame exceeds limit")
        }
        var frame = Data(capacity: body.count + 4)
        let declared = UInt32(body.count).bigEndian
        withUnsafeBytes(of: declared) { frame.append(contentsOf: $0) }
        frame.append(contentsOf: body)
        return frame
    }

    /// Decode one complete frame into a validated envelope.
    public static func decode(
        frame: Data
    ) throws(NativeProtocolError) -> NativeEnvelope {
        try NativeEnvelope.decode(frame: frame)
    }

    /// The JSON body carried by one frame, checking the declared bound before
    /// the body is read, exactly as the Python decoder orders its refusals.
    static func body(of frame: Data) throws(NativeProtocolError) -> Data {
        guard frame.count >= 4 else {
            throw NativeProtocolError(.frameIncomplete, "frame header is incomplete")
        }
        var declared = 0
        for byte in frame.prefix(4) {
            declared = declared << 8 | Int(byte)
        }
        guard declared <= NativeProtocol.maxFrameBytes else {
            throw NativeProtocolError(.frameTooLarge, "native frame exceeds limit")
        }
        let actual = frame.count - 4
        guard actual >= declared else {
            throw NativeProtocolError(.frameIncomplete, "frame body is incomplete")
        }
        guard actual == declared else {
            throw NativeProtocolError(.frameTrailingData, "frame contains trailing data")
        }
        return frame.dropFirst(4)
    }
}
