using System.IO;
using System.Text.Json;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Support;

internal sealed record ProviderOfficeReceipt(
    string CommandId,
    long AcceptedCursor,
    string State,
    long? ResultEventCursor);

internal static class ProviderOfficeReceiptStore
{
    public static ProviderOfficeReceipt Read(string temporaryRoot, string commandId)
    {
        var root = Path.Combine(
            temporaryRoot, "workspace", "workspace", "native-app", "receipts");
        foreach (var path in Directory.EnumerateFiles(root, "*.json"))
        {
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var receipt = document.RootElement;
            if (!string.Equals(receipt.GetProperty("command_id").GetString(), commandId, StringComparison.Ordinal))
            {
                continue;
            }
            return new ProviderOfficeReceipt(
                commandId,
                receipt.GetProperty("accepted_cursor").GetInt64(),
                receipt.GetProperty("state").GetString() ?? string.Empty,
                receipt.GetProperty("result_event_cursor").ValueKind == JsonValueKind.Number
                    ? receipt.GetProperty("result_event_cursor").GetInt64()
                    : null);
        }
        throw new AssertFailedException($"receipt store did not contain command {commandId}");
    }
}
