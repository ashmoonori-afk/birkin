namespace Birkin.Native.Protocol.Framing;

public sealed class NativeProtocolError : Exception
{
    private const int MaxPublicMessageLength = 512;

    public NativeProtocolError(string code, string message)
        : base(message.Length <= MaxPublicMessageLength ? message : message[..MaxPublicMessageLength])
    {
        Code = code;
    }

    public string Code { get; }
}
