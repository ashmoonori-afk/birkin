namespace Birkin.Native.Protocol.Transport;

internal sealed record LoopbackBootstrap(DateTimeOffset ExpiresAt, string Secret);

public sealed class LoopbackDiscoveryRecord
{
    private string? _bootstrapSecret;

    internal LoopbackDiscoveryRecord(int port, BridgeAnnouncement announcement, LoopbackBootstrap bootstrap)
    {
        Port = port;
        InstanceId = announcement.InstanceId;
        ServerVersion = announcement.ServerVersion;
        ExpiresAt = bootstrap.ExpiresAt;
        _bootstrapSecret = bootstrap.Secret;
    }

    public string Host => "127.0.0.1";
    public int Port { get; }
    public string InstanceId { get; }
    public string ServerVersion { get; }
    public DateTimeOffset ExpiresAt { get; }

    public string? TakeBootstrapSecret()
    {
        var secret = _bootstrapSecret;
        _bootstrapSecret = null;
        return secret;
    }
}
