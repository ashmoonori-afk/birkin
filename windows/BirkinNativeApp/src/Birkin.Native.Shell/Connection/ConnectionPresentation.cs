namespace Birkin.Native.Shell.Connection;

public sealed record ConnectionPresentation
{
    private const string FallbackErrorCode = "E_CONNECTION";

    private ConnectionPresentation(ConnectionState state, string statusText, string? errorCode)
    {
        State = state;
        StatusText = statusText;
        ErrorCode = errorCode;
    }

    public ConnectionState State { get; }

    public string StatusText { get; }

    public string? ErrorCode { get; }

    public static ConnectionPresentation Create(ConnectionState state)
    {
        var status = state switch
        {
            ConnectionState.Disconnected => "DISCONNECTED",
            ConnectionState.Connecting => "CONNECTING",
            ConnectionState.Handshaking => "HANDSHAKING",
            ConnectionState.Subscribing => "SUBSCRIBING",
            ConnectionState.Ready => "LOCAL · PRIVATE",
            ConnectionState.Failed => "CONNECTION FAILED",
            _ => throw new ArgumentOutOfRangeException(nameof(state)),
        };
        return new ConnectionPresentation(state, status, null);
    }

    public static ConnectionPresentation Failed(string errorCode)
    {
        var boundedCode = errorCode.Length is > 0 and <= 64
            && errorCode.All(character => character is >= 'A' and <= 'Z' or >= '0' and <= '9' or '_')
                ? errorCode
                : FallbackErrorCode;
        return new ConnectionPresentation(ConnectionState.Failed, "CONNECTION FAILED", boundedCode);
    }
}
