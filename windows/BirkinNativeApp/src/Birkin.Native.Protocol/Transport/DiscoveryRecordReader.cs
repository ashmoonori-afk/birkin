using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Protocol.Transport;

public static class DiscoveryRecordReader
{
    private static readonly HashSet<string> Keys = new(StringComparer.Ordinal)
    {
        "bootstrap_secret", "expires_at", "host", "instance_id", "port", "protocol_versions", "server_version", "transport",
    };

    public static LoopbackDiscoveryRecord Read(string path, BridgeAnnouncement announcement, DateTimeOffset now)
    {
        if (!string.Equals(Path.GetFullPath(path), Path.GetFullPath(announcement.DiscoveryPath), StringComparison.OrdinalIgnoreCase))
        {
            throw Error("E_DISCOVERY_IDENTITY");
        }

        FileInfo file;
        try
        {
            file = new FileInfo(path);
            if (!file.Exists || (file.Attributes & FileAttributes.ReparsePoint) != 0)
            {
                throw Error((file.Attributes & FileAttributes.ReparsePoint) != 0 ? "E_DISCOVERY_REPARSE_POINT" : "E_BOOTSTRAP_INVALID");
            }
        }
        catch (NativeProtocolError)
        {
            throw;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            throw Error("E_BOOTSTRAP_INVALID");
        }

        NativeJsonObject body;
        try
        {
            body = NativeJsonParser.Parse(File.ReadAllBytes(path)) as NativeJsonObject ?? throw Error("E_BOOTSTRAP_INVALID");
        }
        catch (NativeProtocolError)
        {
            throw;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            throw Error("E_BOOTSTRAP_INVALID");
        }

        if (body.Count != Keys.Count || body.Keys.Any(key => !Keys.Contains(key)))
        {
            throw Error("E_BOOTSTRAP_INVALID");
        }
        if (String(body, "transport") != "loopback")
        {
            throw Error("E_TRANSPORT");
        }
        if (String(body, "host") != "127.0.0.1")
        {
            throw Error("E_DISCOVERY_HOST");
        }
        if (body["port"] is not NativeJsonInteger { Value: >= 1 and <= 65535 } port)
        {
            throw Error("E_PORT");
        }
        if (body["protocol_versions"] is not NativeJsonArray versions
            || !versions.Values.Any(value => value is NativeJsonInteger { Value: NativeProtocolConstants.Version })
            || versions.Values.Any(value => value is not NativeJsonInteger))
        {
            throw Error("E_PROTOCOL_VERSION");
        }

        var secret = String(body, "bootstrap_secret");
        if (secret.Length != 43 || secret.Any(character => character is not (>= 'A' and <= 'Z')
            and not (>= 'a' and <= 'z') and not (>= '0' and <= '9') and not '-' and not '_'))
        {
            throw Error("E_BOOTSTRAP_INVALID");
        }
        var expiry = NativeProtocolDate.Parse(String(body, "expires_at"), "E_BOOTSTRAP_INVALID");
        if (now >= expiry)
        {
            throw Error("E_BOOTSTRAP_EXPIRED");
        }

        var instanceId = String(body, "instance_id");
        var serverVersion = String(body, "server_version");
        if (!BridgeAnnouncement.IsInstanceId(instanceId)
            || !string.Equals(instanceId, announcement.InstanceId, StringComparison.Ordinal)
            || !string.Equals(serverVersion, announcement.ServerVersion, StringComparison.Ordinal))
        {
            throw Error("E_DISCOVERY_IDENTITY");
        }

        return new LoopbackDiscoveryRecord(
            checked((int)port.Value),
            announcement,
            new LoopbackBootstrap(expiry, secret));
    }

    private static string String(NativeJsonObject body, string key) =>
        body[key] is NativeJsonString value ? value.Value : throw Error("E_BOOTSTRAP_INVALID");

    private static NativeProtocolError Error(string code) => new(code, "loopback discovery record is invalid");
}
