using System.Text.Json;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Presentation;

[TestClass]
public sealed class WorkspaceSnapshotPresentationTests
{
    [TestMethod]
    public void ApprovalLabels_WhenRendered_AreKoreanDecisionCopy()
    {
        // Given
        var item = new PanelItemPresentation(
            "approval-copy",
            "approval",
            "검토",
            Category: "office_job",
            Risk: "high",
            Sealed: true,
            OverwriteApproved: true,
            Requester: "native:test");

        // Then
        Assert.AreEqual("Office 작업", item.CategoryLabel);
        Assert.AreEqual("높은 위험", item.RiskLabel);
        Assert.AreEqual("검토 내용 고정됨", item.SealedLabel);
        Assert.AreEqual(
            "주의: 기존 파일을 덮어쓸 수 있습니다",
            item.OverwriteLabel);
        Assert.AreEqual("요청자: native:test", item.RequesterLabel);
        Assert.AreEqual(
            "거부하면 이 작업은 실행되지 않습니다.",
            item.RejectionResultLabel);
    }

    [TestMethod]
    public void DestinationDisplay_WhenPathContainsNonBmpText_PreservesScalarBoundariesAndFilename()
    {
        // Given
        var path = "/" + string.Concat(Enumerable.Repeat("😀", 30)) + "/report.xlsx";
        var item = new PanelItemPresentation(
            "approval-unicode",
            "approval",
            "Unicode destination",
            Destination: path);

        // When
        var display = item.DestinationDisplay;

        // Then
        Assert.IsNotNull(display);
        Assert.IsFalse(display.Contains('\uFFFD'));
        Assert.IsTrue(display.EndsWith("report.xlsx", StringComparison.Ordinal));
    }

    [TestMethod]
    public void FromProjection_WhenOfficeApprovalEventIsApplied_MapsTrustDetailsWithoutLoss()
    {
        // Given
        var path = Path.Combine(AppContext.BaseDirectory, "GoldenVectors", "native-projection-vectors.json");
        using var fixture = JsonDocument.Parse(File.ReadAllBytes(path));
        var store = new NativeProjectionStore();
        store.ApplySnapshot(
            Decode(fixture.RootElement.GetProperty("snapshot")),
            new NativeReadyIdentity("session-1", "instance-1", "fixture-version"));
        foreach (var vector in fixture.RootElement.GetProperty("events").EnumerateArray())
        {
            store.ApplyEvent(Decode(vector));
        }

        // When
        var presentation = WorkspaceSnapshotPresentation.FromProjection(store.State!, "loopback");

        // Then
        var approval = presentation.ApprovalRequests.Single(item =>
            string.Equals(item.Id, "approval-vector", StringComparison.Ordinal));
        Assert.AreEqual("approval-vector", approval.Id);
        Assert.AreEqual("Comparison!A1: 7 to 9", approval.Description);
        Assert.AreEqual("high", approval.Risk);
        Assert.IsTrue(approval.Sealed);
        Assert.IsTrue(approval.Decided);
        Assert.AreEqual("comparison-source.xlsx", approval.SourceFilename);
        Assert.AreEqual("/workspace/approved/comparison.xlsx", approval.Destination);
        Assert.AreEqual(false, approval.OverwriteApproved);
        Assert.AreEqual(new string('a', 64), approval.AuthorityDigest);
        Assert.AreEqual("native:session-1", approval.Requester);
        Assert.AreEqual(
            "Rejecting leaves the source unchanged and writes no output.",
            approval.RejectionResult);
    }

    [TestMethod]
    public void FromProjection_WhenPythonGoldenSnapshotIsApplied_MapsCanonicalShellRegionsReadOnly()
    {
        // Given
        var path = Path.Combine(AppContext.BaseDirectory, "GoldenVectors", "native-projection-vectors.json");
        using var fixture = JsonDocument.Parse(File.ReadAllBytes(path));
        var vector = fixture.RootElement.GetProperty("snapshot");
        var frame = Convert.FromBase64String(vector.GetProperty("frame_base64").GetString()!);
        var store = new NativeProjectionStore();
        store.ApplySnapshot(
            NativeFrameCodec.Decode(frame),
            new NativeReadyIdentity("session-1", "instance-1", "fixture-version"));

        // When
        var presentation = WorkspaceSnapshotPresentation.FromProjection(store.State!, "loopback");

        // Then
        Assert.AreEqual("session-1", presentation.SessionId);
        Assert.AreEqual(10, presentation.PanelCount);
        Assert.AreEqual("connected", presentation.PythonConnection);
        Assert.AreEqual(2, presentation.Conversation.Count);
        Assert.AreEqual("user_message", presentation.Conversation[0].Kind);
        Assert.AreEqual("Ship the reducer", presentation.Conversation[0].Text);
        Assert.AreEqual("macos:window-main", presentation.Conversation[0].ActorId);
        Assert.AreEqual("assistant_message", presentation.Conversation[1].Kind);
        Assert.IsTrue(presentation.Composer.CanSend);
        Assert.IsFalse(presentation.Composer.IsEnabled);
        Assert.IsFalse(presentation.MutationAvailability.IsEnabled);
        CollectionAssert.AreEqual(
            new[] { "Goals", "Context", "Files", "Constraints", "Notes" },
            presentation.WorkingMemory.Rows.Select(row => row.Label).ToArray());
        CollectionAssert.AreEqual(
            new[] { "Ship native Working Memory" },
            presentation.WorkingMemory.Rows[0].Values.ToArray());
        CollectionAssert.AreEqual(
            new[] { "Use canonical state", "Delegate to Python", "RED captured" },
            presentation.WorkingMemory.Rows[1].Values.ToArray());
        CollectionAssert.AreEqual(
            new[] { "workspace/main.py" },
            presentation.WorkingMemory.Rows[2].Values.ToArray());
        CollectionAssert.AreEqual(
            new[] { "Stay offline" },
            presentation.WorkingMemory.Rows[3].Values.ToArray());
        CollectionAssert.AreEqual(
            new[] { "Render five rows", "Run GREEN" },
            presentation.WorkingMemory.Rows[4].Values.ToArray());
        Assert.AreEqual(1L, presentation.WorkingMemory.Revision);
        Assert.AreEqual(3, presentation.Approvals.Count);
        Assert.IsTrue(presentation.Approvals.All(row => row.EffectiveState == "Ask"));
        Assert.IsTrue(presentation.Approvals.All(row => row.RequestedState == "Default"));
        Assert.AreEqual(0, presentation.Activity.Count);
        Assert.AreEqual(0, presentation.Browser.Count);
        Assert.AreEqual(0, presentation.Office.Count);
        Assert.IsFalse(presentation.Terminal.IsAvailable);
    }

    [TestMethod]
    public void FromProjected_WhenDiffSummaryIsUnstructured_UsesKoreanFallback()
    {
        var row = OfficeDiffPresentationMapper.FromProjected(
            new PanelItemPresentation(
                "diff-1",
                "diff",
                "unstructured difference"));

        Assert.AreEqual("예상 변경", row.Label);
    }

    private static NativeEnvelope Decode(JsonElement vector) => NativeFrameCodec.Decode(
        Convert.FromBase64String(vector.GetProperty("frame_base64").GetString()!));
}
