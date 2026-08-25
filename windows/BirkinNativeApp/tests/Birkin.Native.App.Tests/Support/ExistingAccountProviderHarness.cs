using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Tests.Support;

internal sealed class ExistingAccountProviderHarness
{
    private readonly string _path;
    private readonly object _gate = new();

    public ExistingAccountProviderHarness(string repositoryRoot)
    {
        _path = Path.Combine(
            repositoryRoot,
            ".omo", "evidence", "native-windows-20260824", "live-chat", "diagnostic.jsonl");
        Directory.CreateDirectory(Path.GetDirectoryName(_path)!);
        File.WriteAllText(_path, string.Empty);
    }

    public string EvidencePath => _path;

    public void Record(string stage, IReadOnlyDictionary<string, object?> values)
    {
        var record = new Dictionary<string, object?>(values, StringComparer.Ordinal)
        {
            ["stage"] = stage,
        };
        lock (_gate)
        {
            File.AppendAllText(_path, JsonSerializer.Serialize(record) + Environment.NewLine);
        }
    }

    public void RecordProjection(WorkspaceSnapshotPresentation snapshot)
    {
        Record("projection", new Dictionary<string, object?>
        {
            ["cursor"] = snapshot.Cursor,
            ["rows"] = snapshot.Conversation.Select(row => new Dictionary<string, object?>
            {
                ["kind"] = row.Kind,
                ["cursor"] = row.Cursor,
                ["text_bytes"] = Encoding.UTF8.GetByteCount(row.Text),
                ["text_sha256"] = Hash(row.Text),
            }).ToArray(),
        });
    }

    public void CaptureWorkspace(string temporaryRoot)
    {
        var sessionRoot = Path.Combine(temporaryRoot, "workspace", "workspace", "native-app");
        var eventsPath = Path.Combine(sessionRoot, "events.jsonl");
        if (File.Exists(eventsPath))
        {
            foreach (var line in File.ReadLines(eventsPath))
            {
                using var document = JsonDocument.Parse(line);
                var root = document.RootElement;
                var payload = root.GetProperty("payload");
                var values = new Dictionary<string, object?>
                {
                    ["cursor"] = root.GetProperty("cursor").GetInt64(),
                    ["kind"] = root.GetProperty("type").GetString(),
                    ["command_id"] = root.GetProperty("command_id").GetString(),
                };
                foreach (var key in new[] { "text", "error" })
                {
                    if (payload.TryGetProperty(key, out var value) && value.ValueKind == JsonValueKind.String)
                    {
                        var text = value.GetString() ?? string.Empty;
                        values[$"{key}_bytes"] = Encoding.UTF8.GetByteCount(text);
                        values[$"{key}_sha256"] = Hash(text);
                    }
                }
                Record("workspace-event", values);
            }
        }

        var receipts = Path.Combine(sessionRoot, "receipts");
        foreach (var receiptPath in Directory.Exists(receipts)
            ? Directory.EnumerateFiles(receipts, "*.json")
            : [])
        {
            using var document = JsonDocument.Parse(File.ReadAllText(receiptPath));
            var root = document.RootElement;
            Record("workspace-receipt", new Dictionary<string, object?>
            {
                ["command_id"] = root.GetProperty("command_id").GetString(),
                ["accepted_cursor"] = root.GetProperty("accepted_cursor").GetInt64(),
                ["state"] = root.GetProperty("state").GetString(),
                ["result_event_cursor"] = root.GetProperty("result_event_cursor").ValueKind == JsonValueKind.Number
                    ? root.GetProperty("result_event_cursor").GetInt64()
                    : null,
            });
        }
    }

    private static string Hash(string value) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant();
}
