using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Transport;

namespace Birkin.Native.Protocol.Messaging;

public sealed record NativeReadyIdentity(string SessionId, string InstanceId, string ServerVersion);

public sealed record NativeSessionCapability(
    string Token,
    DateTimeOffset ExpiresAt,
    DateTimeOffset HardExpiresAt);

public sealed record NativeReadySession(NativeReadyIdentity Identity, NativeSessionCapability SessionCapability)
{
    public string SessionId => Identity.SessionId;
    public string InstanceId => Identity.InstanceId;
    public string ServerVersion => Identity.ServerVersion;
    public string Capability => SessionCapability.Token;
}

public sealed record NativeHandshakeExpectation(
    string HelloId,
    string ProductVersion,
    BridgeAnnouncement Announcement);

public static class NativeHandshake
{
    private const int MaxPayloadBytes = 65_536;
    private const int MaxInflightCommands = 1;
    private const int MaxSubscriptions = 32;

    public static NativeEnvelope CreateHello(string productVersion, string bootstrapSecret, string id)
    {
        var body = Object(
            ("client", new NativeJsonString("birkin-native-windows")),
            ("client_version", new NativeJsonString(productVersion)),
            ("client_build", new NativeJsonString(productVersion)),
            ("supported_protocol_versions", new NativeJsonArray([new NativeJsonInteger(NativeProtocolConstants.Version)])),
            ("surface", new NativeJsonString("windows")),
            ("view_id", new NativeJsonString("window-main")),
            ("bootstrap_secret", new NativeJsonString(bootstrapSecret)));
        var hello = new NativeEnvelope(NativeMessageKind.Hello, id, body);
        NativeBodyValidator.Validate(hello, NativeMessageOrigin.Client);
        return hello;
    }

    public static NativeReadySession ValidateReady(
        NativeEnvelope ready,
        NativeHandshakeExpectation expectation)
    {
        if (ready.Kind == NativeMessageKind.Error)
        {
            NativeBodyValidator.Validate(ready, NativeMessageOrigin.Server);
            throw new NativeProtocolError(String(ready.Body, "code"), String(ready.Body, "message"));
        }
        if (ready.Kind != NativeMessageKind.Ready)
        {
            throw new NativeProtocolError("E_STATE", "ready is required after hello");
        }
        if (!string.Equals(ready.InReplyTo, expectation.HelloId, StringComparison.Ordinal))
        {
            throw new NativeProtocolError("E_CORRELATION", "ready does not correlate to hello");
        }

        NativeBodyValidator.Validate(ready, NativeMessageOrigin.Server);
        var body = ready.Body;
        var serverVersion = String(body, "server_version");
        if (!string.Equals(serverVersion, expectation.ProductVersion, StringComparison.Ordinal)
            || !string.Equals(serverVersion, expectation.Announcement.ServerVersion, StringComparison.Ordinal))
        {
            throw new NativeProtocolError("E_VERSION_MISMATCH", "bridge and client product versions differ");
        }
        var instanceId = String(body, "instance_id");
        if (!string.Equals(instanceId, expectation.Announcement.InstanceId, StringComparison.Ordinal))
        {
            throw new NativeProtocolError("E_DISCOVERY_IDENTITY", "ready identity differs from announcement");
        }
        if (String(body, "transport") != "loopback")
        {
            throw new NativeProtocolError("E_TRANSPORT", "ready transport is not loopback");
        }

        var sessionId = String(body, "session_id");
        if (sessionId.Length is < 1 or > 128)
        {
            throw BodyError();
        }
        var capability = RequireObject(body, "capability");
        var token = String(capability, "token");
        if (token.Length is < 1 or > 512 || !token.All(character => character <= 0x7f))
        {
            throw BodyError();
        }
        var expiresAt = NativeProtocolDate.Parse(String(capability, "expires_at"), "E_BODY");
        var hardExpiresAt = NativeProtocolDate.Parse(String(capability, "hard_expires_at"), "E_BODY");
        if (expiresAt > hardExpiresAt)
        {
            throw BodyError();
        }

        ValidateLimits(RequireObject(body, "limits"));
        var capabilities = RequireObject(body, "capabilities");
        if (capabilities["commands"] is not NativeJsonArray commands
            || commands.Values.Any(value => value is not NativeJsonString)
            || capabilities["panels"] is not NativeJsonArray panels
            || panels.Values.Any(value => value is not NativeJsonString)
            || capabilities["features"] is not NativeJsonObject)
        {
            throw BodyError();
        }

        return new NativeReadySession(
            new NativeReadyIdentity(sessionId, instanceId, serverVersion),
            new NativeSessionCapability(token, expiresAt, hardExpiresAt));
    }

    public static NativeEnvelope CreateSubscribe(NativeReadySession session, string id)
    {
        var subscribe = new NativeEnvelope(
            NativeMessageKind.Subscribe,
            id,
            Object(
                ("session_id", new NativeJsonString(session.SessionId)),
                ("after_cursor", new NativeJsonInteger(0)),
                ("known_instance_id", NativeJsonNull.Value),
                ("session_capability", new NativeJsonString(session.Capability)),
                ("surfaces", new NativeJsonObject())));
        NativeBodyValidator.Validate(subscribe, NativeMessageOrigin.Client);
        return subscribe;
    }

    private static void ValidateLimits(NativeJsonObject limits)
    {
        var maxFrame = PositiveInteger(limits, "max_frame_bytes");
        var maxPayload = PositiveInteger(limits, "max_payload_bytes");
        var maxDepth = PositiveInteger(limits, "max_json_depth");
        var maxInflight = PositiveInteger(limits, "max_inflight_commands");
        var maxSubscriptions = PositiveInteger(limits, "max_subscriptions");
        if (maxFrame > NativeProtocolConstants.MaxFrameBytes || maxPayload > MaxPayloadBytes
            || maxDepth > NativeProtocolConstants.MaxBodyDepth || maxInflight > MaxInflightCommands
            || maxSubscriptions > MaxSubscriptions)
        {
            throw new NativeProtocolError("E_LIMIT", "server limits exceed client safety ceilings");
        }
    }

    private static long PositiveInteger(NativeJsonObject body, string key) =>
        body[key] is NativeJsonInteger { Value: > 0 } integer ? integer.Value : throw BodyError();

    private static NativeJsonObject RequireObject(NativeJsonObject body, string key) =>
        body[key] as NativeJsonObject ?? throw BodyError();

    private static string String(NativeJsonObject body, string key) =>
        body[key] is NativeJsonString text ? text.Value : throw BodyError();

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));

    private static NativeProtocolError BodyError() => new("E_BODY", "handshake body is invalid");
}
