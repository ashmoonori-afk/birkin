using System.Text;
using Birkin.Native.Protocol.Framing;

namespace Birkin.Native.Protocol.Transport;

public sealed record BridgeAnnouncement(
    int ProcessId,
    string Root,
    string SessionId,
    string InstanceId,
    string ServerVersion,
    string DiscoveryPath)
{
    private static readonly HashSet<string> Keys = new(StringComparer.Ordinal)
    {
        "event", "transport", "pid", "root", "session_id", "instance_id", "server_version", "discovery_path",
    };

    public static BridgeAnnouncement Parse(string json)
    {
        NativeJsonObject body;
        try
        {
            body = NativeJsonParser.Parse(Encoding.UTF8.GetBytes(json)) as NativeJsonObject
                ?? throw Error("E_ANNOUNCEMENT");
        }
        catch (NativeProtocolError)
        {
            throw;
        }

        if (body.Count != Keys.Count || body.Keys.Any(key => !Keys.Contains(key)))
        {
            throw Error("E_ANNOUNCEMENT");
        }
        if (String(body, "event") != "listening")
        {
            throw Error("E_ANNOUNCEMENT");
        }
        if (String(body, "transport") != "loopback")
        {
            throw Error("E_TRANSPORT");
        }
        if (body["pid"] is not NativeJsonInteger { Value: > 0 and <= int.MaxValue } pid)
        {
            throw Error("E_ANNOUNCEMENT");
        }

        var root = String(body, "root");
        var sessionId = String(body, "session_id");
        var instanceId = String(body, "instance_id");
        var serverVersion = String(body, "server_version");
        var discoveryPath = String(body, "discovery_path");
        if (!Path.IsPathFullyQualified(root) || !Path.IsPathFullyQualified(discoveryPath)
            || sessionId.Length is < 1 or > 128 || serverVersion.Length is < 1 or > 64
            || !IsInstanceId(instanceId))
        {
            throw Error("E_ANNOUNCEMENT");
        }

        return new BridgeAnnouncement((int)pid.Value, root, sessionId, instanceId, serverVersion, discoveryPath);
    }

    internal static bool IsInstanceId(string value) => value.Length == 32
        && value.All(character => character is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static string String(NativeJsonObject body, string key) =>
        body[key] is NativeJsonString value ? value.Value : throw Error("E_ANNOUNCEMENT");

    private static NativeProtocolError Error(string code) => new(code, "bridge announcement is invalid");
}
