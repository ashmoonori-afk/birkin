using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Birkin.Native.App.Tests.Support;

internal sealed class ProviderOfficeEvidence
{
    private readonly object _gate = new();

    public ProviderOfficeEvidence(string evidenceRoot)
    {
        Directory.CreateDirectory(evidenceRoot);
        DiagnosticPath = Path.Combine(evidenceRoot, "diagnostic.jsonl");
        File.WriteAllText(DiagnosticPath, string.Empty);
    }

    public string DiagnosticPath { get; }

    public void Record(string stage, IReadOnlyDictionary<string, object?> machineValues)
    {
        var record = new Dictionary<string, object?>(machineValues, StringComparer.Ordinal)
        {
            ["stage"] = stage,
        };
        lock (_gate)
        {
            File.AppendAllText(DiagnosticPath, JsonSerializer.Serialize(record) + Environment.NewLine);
        }
    }

    public void RecordText(string stage, string text) => Record(stage, new Dictionary<string, object?>
    {
        ["text_bytes"] = Encoding.UTF8.GetByteCount(text),
        ["text_sha256"] = Hash(text),
    });

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
                var values = new Dictionary<string, object?>
                {
                    ["cursor"] = root.GetProperty("cursor").GetInt64(),
                    ["kind"] = root.GetProperty("type").GetString(),
                    ["command_id"] = root.GetProperty("command_id").GetString(),
                    ["event_id"] = root.GetProperty("event_id").GetString(),
                };
                var payload = root.GetProperty("payload");
                if (payload.TryGetProperty("text", out var value) && value.ValueKind == JsonValueKind.String)
                {
                    var text = value.GetString() ?? string.Empty;
                    values["text_bytes"] = Encoding.UTF8.GetByteCount(text);
                    values["text_sha256"] = Hash(text);
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

    public static string Hash(string value) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant();
}
