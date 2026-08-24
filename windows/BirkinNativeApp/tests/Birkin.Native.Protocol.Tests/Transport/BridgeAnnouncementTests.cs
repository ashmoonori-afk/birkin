using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Transport;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Transport;

[TestClass]
public sealed class BridgeAnnouncementTests
{
    private const string InstanceId = "0123456789abcdef0123456789abcdef";

    [TestMethod]
    public void Parse_WhenRealListeningShapeIsValid_ReturnsTypedAnnouncement()
    {
        // Given
        var discoveryPath = Path.GetFullPath(Path.Combine(Path.GetTempPath(), "birkin", "native", "endpoint.json"));
        var json = $$"""{"event":"listening","transport":"loopback","pid":1904,"root":"{{Path.GetDirectoryName(Path.GetDirectoryName(discoveryPath))!.Replace("\\", "\\\\")}}","session_id":"native-app","instance_id":"{{InstanceId}}","server_version":"0.4.276","discovery_path":"{{discoveryPath.Replace("\\", "\\\\")}}"}""";

        // When
        var announcement = BridgeAnnouncement.Parse(json);

        // Then
        Assert.AreEqual(discoveryPath, announcement.DiscoveryPath);
        Assert.AreEqual(InstanceId, announcement.InstanceId);
        Assert.AreEqual("0.4.276", announcement.ServerVersion);
        Assert.AreEqual("native-app", announcement.SessionId);
    }

    [DataTestMethod]
    [DataRow("{\"event\":\"listening\",\"event\":\"listening\",\"transport\":\"loopback\",\"pid\":1,\"root\":\"C:\\\\\",\"session_id\":\"native-app\",\"instance_id\":\"0123456789abcdef0123456789abcdef\",\"server_version\":\"0.4.276\",\"discovery_path\":\"C:\\\\endpoint.json\"}", "E_DUPLICATE_KEY")]
    [DataRow("{\"event\":\"listening\",\"transport\":\"loopback\",\"pid\":1,\"root\":\"C:\\\\\",\"session_id\":\"native-app\",\"instance_id\":\"0123456789abcdef0123456789abcdef\",\"server_version\":\"0.4.276\",\"discovery_path\":\"C:\\\\endpoint.json\",\"extra\":true}", "E_ANNOUNCEMENT")]
    [DataRow("{\"event\":\"listening\",\"transport\":\"uds\",\"pid\":1,\"root\":\"C:\\\\\",\"session_id\":\"native-app\",\"instance_id\":\"0123456789abcdef0123456789abcdef\",\"server_version\":\"0.4.276\",\"discovery_path\":\"C:\\\\endpoint.json\"}", "E_TRANSPORT")]
    public void Parse_WhenAnnouncementIsUntrusted_RefusesWithStableCode(string json, string code)
    {
        // Given / When
        var error = Assert.ThrowsException<NativeProtocolError>(() => BridgeAnnouncement.Parse(json));

        // Then
        Assert.AreEqual(code, error.Code);
    }
}
