using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Transport;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Transport;

[TestClass]
public sealed class DiscoveryRecordReaderTests
{
    private const string InstanceId = "0123456789abcdef0123456789abcdef";
    private const string Secret = "abcdefghijklmnopqrstuvwxyzABCDEFGH123456789";
    private static readonly DateTimeOffset Now = new(2026, 8, 24, 1, 0, 0, TimeSpan.Zero);

    [TestMethod]
    public void Read_WhenRecordMatchesAnnouncement_ReturnsStrictLoopbackEndpoint()
    {
        // Given
        using var fixture = DiscoveryFixture.Create(Record());

        // When
        var record = DiscoveryRecordReader.Read(fixture.Path, fixture.Announcement, Now);

        // Then
        Assert.AreEqual("127.0.0.1", record.Host);
        Assert.AreEqual(54291, record.Port);
        Assert.AreEqual(Secret, record.TakeBootstrapSecret());
        Assert.IsNull(record.TakeBootstrapSecret());
    }

    [DataTestMethod]
    [DataRow("{\"bootstrap_secret\":\"abcdefghijklmnopqrstuvwxyzABCDEFGH123456789\",\"expires_at\":\"2026-08-24T01:51:29.275364+00:00\",\"host\":\"localhost\",\"instance_id\":\"0123456789abcdef0123456789abcdef\",\"port\":54291,\"protocol_versions\":[1],\"server_version\":\"0.4.276\",\"transport\":\"loopback\"}", "E_DISCOVERY_HOST")]
    [DataRow("{\"bootstrap_secret\":\"short\",\"expires_at\":\"2026-08-24T01:51:29.275364+00:00\",\"host\":\"127.0.0.1\",\"instance_id\":\"0123456789abcdef0123456789abcdef\",\"port\":54291,\"protocol_versions\":[1],\"server_version\":\"0.4.276\",\"transport\":\"loopback\"}", "E_BOOTSTRAP_INVALID")]
    [DataRow("{\"bootstrap_secret\":\"abcdefghijklmnopqrstuvwxyzABCDEFGH123456789\",\"expires_at\":\"2026-08-23T01:51:29+00:00\",\"host\":\"127.0.0.1\",\"instance_id\":\"0123456789abcdef0123456789abcdef\",\"port\":54291,\"protocol_versions\":[1],\"server_version\":\"0.4.276\",\"transport\":\"loopback\"}", "E_BOOTSTRAP_EXPIRED")]
    [DataRow("{\"bootstrap_secret\":\"abcdefghijklmnopqrstuvwxyzABCDEFGH123456789\",\"expires_at\":\"2026-08-24T01:51:29.275364+00:00\",\"host\":\"127.0.0.1\",\"instance_id\":\"0123456789abcdef0123456789abcdef\",\"port\":54291,\"protocol_versions\":[2],\"server_version\":\"0.4.276\",\"transport\":\"loopback\"}", "E_PROTOCOL_VERSION")]
    [DataRow("{\"bootstrap_secret\":\"abcdefghijklmnopqrstuvwxyzABCDEFGH123456789\",\"expires_at\":\"2026-08-24T01:51:29.275364+00:00\",\"host\":\"127.0.0.1\",\"instance_id\":\"0123456789abcdef0123456789abcdef\",\"port\":0,\"protocol_versions\":[1],\"server_version\":\"0.4.276\",\"transport\":\"loopback\"}", "E_PORT")]
    public void Read_WhenRecordViolatesTrustBoundary_RefusesWithStableCode(string json, string code)
    {
        // Given
        using var fixture = DiscoveryFixture.Create(json);

        // When
        var error = Assert.ThrowsException<NativeProtocolError>(() => DiscoveryRecordReader.Read(fixture.Path, fixture.Announcement, Now));

        // Then
        Assert.AreEqual(code, error.Code);
    }

    [TestMethod]
    public void Read_WhenIdentityDisagreesWithAnnouncement_Refuses()
    {
        // Given
        using var fixture = DiscoveryFixture.Create(Record().Replace("0.4.276", "0.4.277", StringComparison.Ordinal));

        // When
        var error = Assert.ThrowsException<NativeProtocolError>(() => DiscoveryRecordReader.Read(fixture.Path, fixture.Announcement, Now));

        // Then
        Assert.AreEqual("E_DISCOVERY_IDENTITY", error.Code);
    }

    private static string Record(int port = 54291) => $$"""{"bootstrap_secret":"{{Secret}}","expires_at":"2026-08-24T01:51:29.275364+00:00","host":"127.0.0.1","instance_id":"{{InstanceId}}","port":{{port}},"protocol_versions":[1],"server_version":"0.4.276","transport":"loopback"}""";

    private sealed class DiscoveryFixture : IDisposable
    {
        private DiscoveryFixture(string directory, string path, BridgeAnnouncement announcement)
        {
            Directory = directory;
            Path = path;
            Announcement = announcement;
        }

        public string Directory { get; }
        public string Path { get; }
        public BridgeAnnouncement Announcement { get; }

        public static DiscoveryFixture Create(string json)
        {
            var directory = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"birkin-discovery-{Guid.NewGuid():N}");
            System.IO.Directory.CreateDirectory(directory);
            var path = System.IO.Path.Combine(directory, "endpoint.json");
            File.WriteAllText(path, json);
            var root = System.IO.Path.GetDirectoryName(directory)!;
            var announcement = BridgeAnnouncement.Parse($$"""{"event":"listening","transport":"loopback","pid":1904,"root":"{{root.Replace("\\", "\\\\")}}","session_id":"native-app","instance_id":"{{InstanceId}}","server_version":"0.4.276","discovery_path":"{{path.Replace("\\", "\\\\")}}"}""");
            return new DiscoveryFixture(directory, path, announcement);
        }

        public void Dispose() => System.IO.Directory.Delete(Directory, true);
    }
}
