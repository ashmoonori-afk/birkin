using System.IO;
using System.Text.Json;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Support;

[TestClass]
public sealed class ProviderOfficeEvidenceTests
{
    [TestMethod]
    public void RecordText_WritesOnlyLengthAndSha256()
    {
        var root = Path.Combine(Path.GetTempPath(), $"birkin-provider-evidence-{Guid.NewGuid():N}");
        try
        {
            var evidence = new ProviderOfficeEvidence(root);
            const string sensitive = "provider output that must never be logged";

            evidence.RecordText("assistant", sensitive);

            var diagnostic = File.ReadAllText(evidence.DiagnosticPath);
            Assert.IsFalse(diagnostic.Contains(sensitive, StringComparison.Ordinal));
            StringAssert.Contains(diagnostic, "text_bytes");
            StringAssert.Contains(diagnostic, "text_sha256");
        }
        finally
        {
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    [TestMethod]
    public void CaptureWorkspace_RetainsOnlyBoundedOfficeFailureDiagnostic()
    {
        var root = Path.Combine(Path.GetTempPath(), $"birkin-provider-evidence-{Guid.NewGuid():N}");
        try
        {
            var eventRoot = Path.Combine(root, "workspace", "workspace", "native-app");
            Directory.CreateDirectory(eventRoot);
            File.WriteAllLines(Path.Combine(eventRoot, "events.jsonl"),
            [
                Event("item-valid", "{\"operation_count\":2,\"locator_shapes\":[\"public_docx_positive_index\",\"native_or_extra_locator\"],\"error_code\":\"INVALID_INPUT\",\"error_stage\":\"plan\",\"secret_marker\":\"DO_NOT_RETAIN\"}"),
                Event("item-invalid-count", "{\"operation_count\":\"two\",\"locator_shapes\":[\"invalid_docx_index\"],\"arbitrary\":\"DO_NOT_RETAIN\"}"),
                "{\"cursor\":2,\"type\":\"tool.failed\",\"command_id\":\"command-1\",\"event_id\":\"event-2\",\"payload\":{\"runtime_name\":\"office_job_request\",\"runtime_server\":{},\"runtime_tool_status\":\"failed\",\"runtime_diagnostic\":{\"secret_marker\":\"DO_NOT_RETAIN\"}}}",
            ]);
            var evidence = new ProviderOfficeEvidence(Path.Combine(root, "evidence"));

            evidence.CaptureWorkspace(root);

            var rows = File.ReadLines(evidence.DiagnosticPath).Select(line => JsonDocument.Parse(line)).ToArray();
            var diagnostics = rows.Where(row => row.RootElement.TryGetProperty("runtime_diagnostic", out _))
                .Select(row => row.RootElement.GetProperty("runtime_diagnostic")).ToArray();
            Assert.AreEqual(2, diagnostics.Length);
            Assert.AreEqual(2, diagnostics[0].GetProperty("operation_count").GetInt32());
            Assert.AreEqual("public_docx_positive_index", diagnostics[0].GetProperty("locator_shapes")[0].GetString());
            Assert.IsFalse(diagnostics[1].TryGetProperty("operation_count", out _));
            Assert.AreEqual("invalid_docx_index", diagnostics[1].GetProperty("locator_shapes")[0].GetString());
            Assert.IsFalse(File.ReadAllText(evidence.DiagnosticPath).Contains("DO_NOT_RETAIN", StringComparison.Ordinal));
            foreach (var row in rows) row.Dispose();
        }
        finally
        {
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }

        static string Event(string itemId, string diagnostic) =>
            "{\"cursor\":1,\"type\":\"tool.failed\",\"command_id\":\"command-1\",\"event_id\":\"event-1\",\"payload\":{\"runtime_name\":\"office_job_request\",\"runtime_server\":\"birkin\",\"runtime_item_id\":\""
            + itemId + "\",\"runtime_tool_status\":\"failed\",\"runtime_diagnostic\":" + diagnostic + "}}";
    }
}
