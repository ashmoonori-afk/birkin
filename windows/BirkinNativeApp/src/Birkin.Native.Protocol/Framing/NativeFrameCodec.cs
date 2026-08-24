using System.Buffers.Binary;

namespace Birkin.Native.Protocol.Framing;

public static class NativeFrameCodec
{
    public static NativeEnvelope Decode(ReadOnlySpan<byte> frame)
    {
        if (frame.Length < sizeof(uint))
        {
            throw new NativeProtocolError("E_FRAME_INCOMPLETE", "frame header is incomplete");
        }

        var declared = BinaryPrimitives.ReadUInt32BigEndian(frame);
        if (declared > NativeProtocolConstants.MaxFrameBytes)
        {
            throw new NativeProtocolError("E_FRAME_TOO_LARGE", "native frame exceeds limit");
        }

        var actual = frame.Length - sizeof(uint);
        if (actual < declared)
        {
            throw new NativeProtocolError("E_FRAME_INCOMPLETE", "frame body is incomplete");
        }

        if (actual > declared)
        {
            throw new NativeProtocolError("E_FRAME_TRAILING_DATA", "frame contains trailing data");
        }

        return NativeEnvelope.FromJsonValue(NativeJsonParser.Parse(frame[sizeof(uint)..]));
    }

    public static byte[] Encode(NativeEnvelope envelope)
    {
        var body = NativeJsonSerializer.Serialize(envelope.ToJsonValue());
        if (body.Length > NativeProtocolConstants.MaxFrameBytes)
        {
            throw new NativeProtocolError("E_FRAME_TOO_LARGE", "native frame exceeds limit");
        }

        var frame = new byte[body.Length + sizeof(uint)];
        BinaryPrimitives.WriteUInt32BigEndian(frame, (uint)body.Length);
        body.CopyTo(frame.AsSpan(sizeof(uint)));
        return frame;
    }
}
