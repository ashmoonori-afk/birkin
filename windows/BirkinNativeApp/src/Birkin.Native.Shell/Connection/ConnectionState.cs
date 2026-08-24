namespace Birkin.Native.Shell.Connection;

public enum ConnectionState
{
    Disconnected,
    Connecting,
    Handshaking,
    Subscribing,
    Ready,
    Failed,
}
