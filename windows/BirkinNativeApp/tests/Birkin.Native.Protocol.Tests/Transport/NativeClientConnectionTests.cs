using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Tests.Messaging;
using Birkin.Native.Protocol.Tests.Support;
using Birkin.Native.Protocol.Transport;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Transport;

[TestClass]
public sealed class NativeClientConnectionTests
{
    private const string Version = "0.4.276";
    private const string InstanceId = "0123456789abcdef0123456789abcdef";
    private const string Secret = "abcdefghijklmnopqrstuvwxyzABCDEFGH123456789";

    [TestMethod]
    public async Task ConnectAsync_WhenFakeServerReturnsReady_CompletesHelloReadySubscribe()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = DiscoveryFile.Create(server.Port);
        await using var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var connect = connection.ConnectAsync(discovery.Announcement, Version, deadline.Token);

        // When
        var hello = await server.ReceiveAsync();
        Assert.AreEqual(Secret, ((NativeJsonString)hello.Body["bootstrap_secret"]!).Value);
        await server.SendAsync(NativeHandshakeTests.Ready(hello.Id));
        await connect;
        var subscribe = await server.ReceiveAsync();

        // Then
        Assert.AreEqual(NativeMessageKind.Subscribe, subscribe.Kind);
        Assert.AreEqual("native-app", ((NativeJsonString)subscribe.Body["session_id"]!).Value);
        Assert.IsFalse(connection.ContainsBootstrapSecretForTesting);
    }

    [TestMethod]
    public async Task ConnectAsync_WhenReadyAdvertisesCommands_ExposesSetUntilDisconnect()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = DiscoveryFile.Create(server.Port);
        var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var connect = connection.ConnectAsync(discovery.Announcement, Version, deadline.Token);
        var hello = await server.ReceiveAsync();
        await server.SendAsync(NativeHandshakeTests.Ready(
            hello.Id,
            commands: ["chat.send", "file.import"]));

        // When
        await connect;
        _ = await server.ReceiveAsync();
        var advertisedWhileConnected = connection.AdvertisedCommands.ToArray();
        var live = connection.HasLiveCapability(DateTimeOffset.Parse("2026-08-24T01:00:00+00:00"));
        var expired = connection.HasLiveCapability(DateTimeOffset.Parse("2026-08-24T02:00:00+00:00"));
        await connection.DisposeAsync();

        // Then
        CollectionAssert.AreEquivalent(
            new[] { "chat.send", "file.import" },
            advertisedWhileConnected);
        Assert.IsTrue(live);
        Assert.IsFalse(expired);
        Assert.AreEqual(0, connection.AdvertisedCommands.Count);
    }

    [TestMethod]
    public async Task ReceiveAsync_WhenServerReusesRecentFrameId_RefusesReplay()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        using var discovery = DiscoveryFile.Create(server.Port);
        await using var connection = new NativeClientConnection();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var connect = connection.ConnectAsync(discovery.Announcement, Version, deadline.Token);
        var hello = await server.ReceiveAsync();
        var ready = NativeHandshakeTests.Ready(hello.Id);
        await server.SendAsync(ready);
        await connect;
        _ = await server.ReceiveAsync();
        var snapshot = new NativeEnvelope(NativeMessageKind.Snapshot, ready.Id, new NativeJsonObject());
        await server.SendAsync(snapshot);

        // When
        var error = await Assert.ThrowsExceptionAsync<NativeProtocolError>(() => connection.ReceiveAsync(deadline.Token).AsTask());

        // Then
        Assert.AreEqual("E_DUPLICATE_FRAME_ID", error.Code);
    }

    private sealed class DiscoveryFile : IDisposable
    {
        private DiscoveryFile(string directory, BridgeAnnouncement announcement)
        {
            Directory = directory;
            Announcement = announcement;
        }

        public string Directory { get; }
        public BridgeAnnouncement Announcement { get; }

        public static DiscoveryFile Create(int port)
        {
            var directory = Path.Combine(Path.GetTempPath(), $"birkin-client-{Guid.NewGuid():N}");
            System.IO.Directory.CreateDirectory(directory);
            var path = Path.Combine(directory, "endpoint.json");
            File.WriteAllText(path, $$"""{"bootstrap_secret":"{{Secret}}","expires_at":"{{DateTimeOffset.UtcNow.AddMinutes(1):O}}","host":"127.0.0.1","instance_id":"{{InstanceId}}","port":{{port}},"protocol_versions":[1],"server_version":"{{Version}}","transport":"loopback"}""");
            var escapedPath = path.Replace("\\", "\\\\");
            var escapedRoot = directory.Replace("\\", "\\\\");
            var announcement = BridgeAnnouncement.Parse($$"""{"event":"listening","transport":"loopback","pid":1904,"root":"{{escapedRoot}}","session_id":"native-app","instance_id":"{{InstanceId}}","server_version":"{{Version}}","discovery_path":"{{escapedPath}}"}""");
            return new DiscoveryFile(directory, announcement);
        }

        public void Dispose() => System.IO.Directory.Delete(Directory, true);
    }
}
