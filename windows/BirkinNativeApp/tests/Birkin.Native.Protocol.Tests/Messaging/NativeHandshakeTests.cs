using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Transport;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Messaging;

[TestClass]
public sealed class NativeHandshakeTests
{
    private const string Version = "0.4.276";
    private const string InstanceId = "0123456789abcdef0123456789abcdef";

    [TestMethod]
    public void CreateHello_WhenGivenProductIdentity_UsesExactWindowsSchema()
    {
        // Given / When
        var hello = NativeHandshake.CreateHello(Version, "secret", "client-1");

        // Then
        NativeBodyValidator.Validate(hello, NativeMessageOrigin.Client);
        Assert.AreEqual("birkin-native-windows", String(hello.Body, "client"));
        Assert.AreEqual(Version, String(hello.Body, "client_version"));
        Assert.AreEqual(Version, String(hello.Body, "client_build"));
        Assert.AreEqual("windows", String(hello.Body, "surface"));
        Assert.AreEqual("window-main", String(hello.Body, "view_id"));
        CollectionAssert.AreEqual(new long[] { 1 }, ((NativeJsonArray)hello.Body["supported_protocol_versions"]!).Values.Cast<NativeJsonInteger>().Select(value => value.Value).ToArray());
    }

    [TestMethod]
    public void ValidateReady_WhenCorrelatedAndSafe_ReturnsSessionUsedBySubscribe()
    {
        // Given
        var announcement = Announcement();
        var ready = Ready("client-1");

        // When
        var session = NativeHandshake.ValidateReady(
            ready,
            new NativeHandshakeExpectation("client-1", Version, announcement));
        var subscribe = NativeHandshake.CreateSubscribe(session, "client-2");

        // Then
        Assert.AreEqual("native-app", String(subscribe.Body, "session_id"));
        Assert.AreEqual("capability-token", String(subscribe.Body, "session_capability"));
        Assert.IsInstanceOfType<NativeJsonNull>(subscribe.Body["known_instance_id"]);
        Assert.AreEqual(0L, ((NativeJsonInteger)subscribe.Body["after_cursor"]!).Value);
        Assert.AreEqual(0, ((NativeJsonObject)subscribe.Body["surfaces"]!).Count);
    }

    [DataTestMethod]
    [DataRow("different", Version, "E_CORRELATION")]
    [DataRow("client-1", "0.4.277", "E_VERSION_MISMATCH")]
    public void ValidateReady_WhenNegotiationDisagrees_RefusesWithStableCode(string reply, string serverVersion, string code)
    {
        // Given
        var ready = Ready(reply, serverVersion);

        // When
        var error = Assert.ThrowsException<NativeProtocolError>(() => NativeHandshake.ValidateReady(
            ready,
            new NativeHandshakeExpectation("client-1", Version, Announcement())));

        // Then
        Assert.AreEqual(code, error.Code);
    }

    internal static NativeEnvelope Ready(string reply, string serverVersion = Version) => new(
        NativeMessageKind.Ready,
        new NativeEnvelopeIdentity("server-1", reply),
        new NativeJsonObject(new KeyValuePair<string, NativeJsonValue>[]
        {
            new("protocol_version", new NativeJsonInteger(1)),
            new("server_version", new NativeJsonString(serverVersion)),
            new("instance_id", new NativeJsonString(InstanceId)),
            new("session_id", new NativeJsonString("native-app")),
            new("transport", new NativeJsonString("loopback")),
            new("capability", Object(("token", new NativeJsonString("capability-token")), ("expires_at", new NativeJsonString("2026-08-24T02:00:00+00:00")), ("hard_expires_at", new NativeJsonString("2026-08-24T08:00:00+00:00")))),
            new("limits", Object(("max_frame_bytes", new NativeJsonInteger(262144)), ("max_payload_bytes", new NativeJsonInteger(65536)), ("max_json_depth", new NativeJsonInteger(12)), ("max_inflight_commands", new NativeJsonInteger(1)), ("max_subscriptions", new NativeJsonInteger(32)))),
            new("capabilities", Object(("commands", new NativeJsonArray(Array.Empty<NativeJsonValue>())), ("panels", new NativeJsonArray(Array.Empty<NativeJsonValue>())), ("features", new NativeJsonObject()))),
        }));

    internal static BridgeAnnouncement Announcement() => BridgeAnnouncement.Parse($$"""{"event":"listening","transport":"loopback","pid":1904,"root":"C:\\root","session_id":"native-app","instance_id":"{{InstanceId}}","server_version":"{{Version}}","discovery_path":"C:\\root\\native\\endpoint.json"}""");

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) => new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));
    private static string String(NativeJsonObject body, string key) => ((NativeJsonString)body[key]!).Value;
}
