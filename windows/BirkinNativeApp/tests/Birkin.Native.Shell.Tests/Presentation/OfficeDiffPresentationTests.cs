using Birkin.Native.Protocol.Framing;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Presentation;

[TestClass]
public sealed class OfficeDiffPresentationTests
{
    [TestMethod]
    public void ApplyApprovalReceipt_WhenDiffIsCorrelated_MarksDiffApproved()
    {
        // Given
        var current = new OfficeDiffPresentation(
            "diff-7",
            [new OfficeDiffRowPresentation("cell 1", "7", "9")],
            OfficeDiffApprovalState.BeforeApproval);
        var receipt = new NativeEnvelope(
            NativeMessageKind.Event,
            "event-receipt-7",
            Object(
                ("type", Text("receipt.recorded")),
                ("payload", Object(
                    ("diff_id", Text("diff-7")),
                    ("approval_id", Text("approval-7")),
                    ("artifact_id", Text("artifact-7"))))));

        // When
        var updated = OfficeDiffPresentationMapper.ApplyApprovalReceipt(
            current,
            receipt);

        // Then
        Assert.AreEqual(OfficeDiffApprovalState.Approved, updated.ApprovalState);
    }

    private static NativeJsonString Text(string value) => new(value);

    private static NativeJsonObject Object(
        params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair =>
            new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));
}
