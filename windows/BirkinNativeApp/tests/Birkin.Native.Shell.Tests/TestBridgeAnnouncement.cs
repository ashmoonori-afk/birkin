namespace Birkin.Native.Shell.Tests;

internal static class TestBridgeAnnouncement
{
    private const string InstanceId = "0123456789abcdef0123456789abcdef";

    public static string Json(int processId = 1)
    {
        var root = Path.GetFullPath(Path.Combine(Path.GetTempPath(), "birkin-shell-tests"));
        var discoveryPath = Path.Combine(root, "native", "endpoint.json");
        return $$"""{"event":"listening","transport":"loopback","pid":{{processId}},"root":"{{Escape(root)}}","session_id":"session-1","instance_id":"{{InstanceId}}","server_version":"0.4.276","discovery_path":"{{Escape(discoveryPath)}}"}""";
    }

    private static string Escape(string path) => path.Replace("\\", "\\\\", StringComparison.Ordinal);
}
