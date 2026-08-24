using System.Security.Cryptography;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Birkin.Native.Protocol.Framing;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Support;

internal static class ProviderOfficeJourneyAssertions
{
    public static void AssertDeterministicDiff(
        IReadOnlyDictionary<string, NativeJsonObject> artifacts,
        NativeJsonObject diff,
        string diffId)
    {
        var identity = $"{{\"left\":\"{String(artifacts["baseline.xlsx"], "content_hash")}\",\"right\":\"{String(artifacts["candidate.xlsx"], "content_hash")}\",\"version\":{Integer(diff, "version")}}}";
        var expected = $"diff-{Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(identity))).ToLowerInvariant()[..32]}";
        Assert.AreEqual(expected, diffId);
        var serialized = Encoding.UTF8.GetString(NativeJsonSerializer.Serialize(diff));
        StringAssert.Contains(serialized, "4100");
        StringAssert.Contains(serialized, "4700");
    }

    public static void AssertReceiptCorrelation(
        NativeJsonObject payload,
        string approvalId,
        string artifactId,
        string draftId,
        string diffId,
        string requestCommandId,
        string approvalCommandId)
    {
        Assert.AreEqual(approvalId, String(payload, "approval_id"));
        Assert.AreEqual(artifactId, String(payload, "artifact_id"));
        Assert.AreEqual(draftId, String(payload, "draft_id"));
        Assert.AreEqual(diffId, String(payload, "diff_id"));
        Assert.AreEqual(requestCommandId, String(payload, "request_command_id"));
        Assert.AreEqual(approvalCommandId, String(payload, "approval_command_id"));
    }

    public static void AssertStoredReceipts(
        string root,
        IReadOnlyList<ProviderOfficeCommandTrace> traces,
        ProviderOfficeEvidence evidence)
    {
        foreach (var trace in traces)
        {
            var receipt = ProviderOfficeReceiptStore.Read(root, trace.CommandId);
            Assert.AreEqual("completed", receipt.State);
            Assert.AreEqual(trace.CompletionCursor, receipt.ResultEventCursor);
            Assert.IsTrue(receipt.AcceptedCursor <= trace.CompletionCursor);
            evidence.Record("correlated-receipt", new Dictionary<string, object?>
            {
                ["command_id"] = trace.CommandId,
                ["accepted_cursor"] = receipt.AcceptedCursor,
                ["result_event_cursor"] = receipt.ResultEventCursor,
            });
        }
    }

    public static void AssertActivityAndOfficeUi(DependencyObject window, string artifactId)
    {
        var activity = OfficeWorkflowViewHarness.Find<FrameworkElement>(window, "activity.landmark");
        Assert.IsTrue(Descendants<TextBlock>(activity).Any(text =>
            string.Equals(text.Text, "Approved Office report saved and structurally verified", StringComparison.Ordinal)));
        var office = OfficeWorkflowViewHarness.Find<FrameworkElement>(window, "office.landmark");
        Assert.IsTrue(Descendants<TextBlock>(office).Any(text =>
            text.Text.Contains(artifactId, StringComparison.Ordinal)));
    }

    private static IEnumerable<T> Descendants<T>(DependencyObject root) where T : DependencyObject
    {
        for (var index = 0; index < VisualTreeHelper.GetChildrenCount(root); index++)
        {
            var child = VisualTreeHelper.GetChild(root, index);
            if (child is T match)
            {
                yield return match;
            }
            foreach (var descendant in Descendants<T>(child))
            {
                yield return descendant;
            }
        }
    }

    private static string String(NativeJsonObject value, string key) =>
        ProviderOfficeEventLog.String(value, key);

    private static long Integer(NativeJsonObject value, string key) =>
        ProviderOfficeEventLog.Integer(value, key);
}
