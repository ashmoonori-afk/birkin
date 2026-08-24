using System.Buffers.Binary;
using System.Net;
using System.Net.Sockets;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Tests.Messaging;
using Birkin.Native.Protocol.Transport;

namespace Birkin.Native.Protocol.Tests.Support;

internal sealed class LoopbackServerHarness : IAsyncDisposable
{
    private readonly TcpListener _listener = new(IPAddress.Loopback, 0);
    private readonly CancellationTokenSource _deadline = new(TimeSpan.FromSeconds(5));
    private Task<TcpClient> _accepted;
    private TcpClient? _client;

    public LoopbackServerHarness()
    {
        _listener.Start();
        Port = ((IPEndPoint)_listener.LocalEndpoint).Port;
        _accepted = _listener.AcceptTcpClientAsync(_deadline.Token).AsTask();
    }

    public int Port { get; }

    public async Task<NativeEnvelope> ReceiveAsync()
    {
        var stream = await GetStreamAsync().ConfigureAwait(false);
        var header = new byte[sizeof(uint)];
        await stream.ReadExactlyAsync(header, _deadline.Token).ConfigureAwait(false);
        var length = BinaryPrimitives.ReadUInt32BigEndian(header);
        if (length > NativeProtocolConstants.MaxFrameBytes)
        {
            throw new InvalidDataException("test server received an oversized frame");
        }

        var body = new byte[checked((int)length)];
        await stream.ReadExactlyAsync(body, _deadline.Token).ConfigureAwait(false);
        return NativeFrameCodec.Decode([.. header, .. body]);
    }

    public async Task SendAsync(NativeEnvelope envelope)
    {
        var stream = await GetStreamAsync().ConfigureAwait(false);
        await stream.WriteAsync(NativeFrameCodec.Encode(envelope), _deadline.Token).ConfigureAwait(false);
    }

    public async Task CompleteHandshakeAsync(
        NativeClientConnection connection,
        TestDiscovery discovery,
        CancellationToken cancellationToken)
    {
        var connecting = connection.ConnectAsync(discovery.Announcement, TestDiscovery.Version, cancellationToken);
        var hello = await ReceiveAsync().ConfigureAwait(false);
        await SendAsync(NativeHandshakeTests.Ready(hello.Id)).ConfigureAwait(false);
        await connecting.ConfigureAwait(false);
        _ = await ReceiveAsync().ConfigureAwait(false);
    }

    public async Task DisconnectClientAsync()
    {
        var client = await _accepted.ConfigureAwait(false);
        client.Dispose();
        _client = null;
        _accepted = _listener.AcceptTcpClientAsync(_deadline.Token).AsTask();
    }

    public async ValueTask DisposeAsync()
    {
        _deadline.Cancel();
        _listener.Dispose();
        if (_client is null)
        {
            try
            {
                _client = await _accepted.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
            }
        }
        _client?.Dispose();
        _deadline.Dispose();
    }

    private async Task<NetworkStream> GetStreamAsync()
    {
        _client ??= await _accepted.ConfigureAwait(false);
        return _client.GetStream();
    }
}

internal sealed class TestDiscovery : IDisposable
{
    public const string Version = "0.4.276";
    public const string InstanceId = "0123456789abcdef0123456789abcdef";
    private const string Secret = "abcdefghijklmnopqrstuvwxyzABCDEFGH123456789";

    private TestDiscovery(string directory, BridgeAnnouncement announcement)
    {
        Directory = directory;
        Announcement = announcement;
    }

    public string Directory { get; }

    public BridgeAnnouncement Announcement { get; }

    public static TestDiscovery Create(int port)
    {
        var directory = Path.Combine(Path.GetTempPath(), $"birkin-lifecycle-{Guid.NewGuid():N}");
        System.IO.Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, "endpoint.json");
        WriteRecord(path, port);
        var escapedPath = path.Replace("\\", "\\\\", StringComparison.Ordinal);
        var escapedRoot = directory.Replace("\\", "\\\\", StringComparison.Ordinal);
        var announcement = BridgeAnnouncement.Parse($$"""{"event":"listening","transport":"loopback","pid":1904,"root":"{{escapedRoot}}","session_id":"native-app","instance_id":"{{InstanceId}}","server_version":"{{Version}}","discovery_path":"{{escapedPath}}"}""");
        return new TestDiscovery(directory, announcement);
    }

    public void Refresh(int port) => WriteRecord(Path.Combine(Directory, "endpoint.json"), port);

    public void Dispose() => System.IO.Directory.Delete(Directory, true);

    private static void WriteRecord(string path, int port) => File.WriteAllText(
        path,
        $$"""{"bootstrap_secret":"{{Secret}}","expires_at":"{{DateTimeOffset.UtcNow.AddMinutes(1):O}}","host":"127.0.0.1","instance_id":"{{InstanceId}}","port":{{port}},"protocol_versions":[1],"server_version":"{{Version}}","transport":"loopback"}""");
}
