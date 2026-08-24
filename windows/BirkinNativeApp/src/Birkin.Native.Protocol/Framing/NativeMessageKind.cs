namespace Birkin.Native.Protocol.Framing;

public sealed record NativeMessageKind
{
    private NativeMessageKind(string wireName)
    {
        WireName = wireName;
    }

    public string WireName { get; }

    public static NativeMessageKind Hello { get; } = new("hello");
    public static NativeMessageKind Ready { get; } = new("ready");
    public static NativeMessageKind Subscribe { get; } = new("subscribe");
    public static NativeMessageKind Snapshot { get; } = new("snapshot");
    public static NativeMessageKind Event { get; } = new("event");
    public static NativeMessageKind SurfaceSnapshot { get; } = new("surface_snapshot");
    public static NativeMessageKind SurfaceEvent { get; } = new("surface_event");
    public static NativeMessageKind Command { get; } = new("command");
    public static NativeMessageKind Receipt { get; } = new("receipt");
    public static NativeMessageKind Error { get; } = new("error");
    public static NativeMessageKind CapabilityRenewed { get; } = new("capability.renewed");
    public static NativeMessageKind StreamDesynchronized { get; } = new("stream.desynchronized");
    public static NativeMessageKind Ping { get; } = new("ping");
    public static NativeMessageKind Pong { get; } = new("pong");
    public static NativeMessageKind Goodbye { get; } = new("goodbye");

    public static IReadOnlyList<NativeMessageKind> All { get; } = Array.AsReadOnly(
        new[]
        {
            Hello, Ready, Subscribe, Snapshot, Event, SurfaceSnapshot, SurfaceEvent,
            Command, Receipt, Error, CapabilityRenewed, StreamDesynchronized, Ping, Pong, Goodbye,
        });

    public static NativeMessageKind Parse(string wireName) =>
        All.FirstOrDefault(kind => string.Equals(kind.WireName, wireName, StringComparison.Ordinal))
        ?? throw new NativeProtocolError("E_KIND", "unsupported native message kind");
}
