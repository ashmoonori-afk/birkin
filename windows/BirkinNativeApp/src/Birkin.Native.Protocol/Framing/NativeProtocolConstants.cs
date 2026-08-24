namespace Birkin.Native.Protocol.Framing;

public static class NativeProtocolConstants
{
    public const string Name = "birkin-local-1";
    public const int Version = 1;
    public const uint MaxFrameBytes = 262_144;
    public const int MaxBodyDepth = 12;
    public const int MaxParserDepth = 128;
}
