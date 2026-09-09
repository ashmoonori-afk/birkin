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
                foreach (var key in new[] { "runtime_name", "runtime_server", "runtime_item_id", "runtime_tool_status" })
                {
                    if (payload.TryGetProperty(key, out var runtimeValue) && runtimeValue.ValueKind == JsonValueKind.String)
                    {
                        values[key] = runtimeValue.GetString();
                    }
                }
                if (root.GetProperty("type").GetString() == "tool.failed"
                    && payload.TryGetProperty("runtime_server", out var runtimeServer) && runtimeServer.ValueKind == JsonValueKind.String && runtimeServer.GetString() == "birkin"
                    && payload.TryGetProperty("runtime_name", out var runtimeName) && runtimeName.ValueKind == JsonValueKind.String && runtimeName.GetString() == "office_job_request"
                    && payload.TryGetProperty("runtime_tool_status", out var toolStatus) && toolStatus.ValueKind == JsonValueKind.String && toolStatus.GetString() == "failed"
                    && payload.TryGetProperty("runtime_diagnostic", out var diagnostic)
                    && diagnostic.ValueKind == JsonValueKind.Object)
                {
                    var bounded = new Dictionary<string, object?>();
                    if (diagnostic.TryGetProperty("operation_count", out var count)
                        && (count.ValueKind == JsonValueKind.Null
                            || count.ValueKind == JsonValueKind.Number && count.TryGetInt32(out var operationCount) && operationCount >= 0))
                    {
                        bounded["operation_count"] = count.ValueKind == JsonValueKind.Number ? count.GetInt32() : null;
                    }
                    if (diagnostic.TryGetProperty("locator_shapes", out var shapes) && shapes.ValueKind == JsonValueKind.Array)
                    {
                        var allowedShapes = new HashSet<string>(["non_object_operation", "non_locator_operation", "non_object_locator", "native_or_extra_locator", "non_docx_locator", "public_docx_positive_index", "invalid_docx_index"]);
                        var shapeValues = shapes.EnumerateArray().Take(11).ToArray();
                        if (shapeValues.Length <= 10 && shapeValues.All(item => item.ValueKind == JsonValueKind.String && allowedShapes.Contains(item.GetString()!)))
                        {
                            bounded["locator_shapes"] = shapeValues.Select(item => item.GetString()).ToArray();
                        }
                    }
                    foreach (var item in new[]
                    {
                        (Key: "error_code", Allowed: new HashSet<string>(["INVALID_INPUT", "PRECONDITION_FAILED", "NODE_NOT_FOUND", "UNSUPPORTED_EDIT"])),
                        (Key: "error_stage", Allowed: new HashSet<string>(["plan", "preview", "locate", "apply"])),
                    })
                    {
                        if (diagnostic.TryGetProperty(item.Key, out var diagnosticValue) && diagnosticValue.ValueKind == JsonValueKind.String
                            && item.Allowed.Contains(diagnosticValue.GetString()!))
                        {
                            bounded[item.Key] = diagnosticValue.GetString();
                        }
                    }
                    values["runtime_diagnostic"] = bounded;
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
