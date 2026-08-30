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
    public void FromProjection_WhenReceiptRecorded_MapsRollbackTrustDetails()
    {
        // Given
        var state = ReceiptProjection();

        // When
        var presentation = WorkspaceSnapshotPresentation.FromProjection(state, "loopback");

        // Then
        var row = presentation.ApprovalRequests.Single();
        Assert.AreEqual("office:job-7", row.ReceiptRef);
        Assert.AreEqual("Approved", row.OutcomeLabel);
        Assert.IsTrue(row.Decided);
        Assert.IsTrue(row.BackupExists);
        Assert.AreEqual(
            "원본은 백업되었으며 9월 28일까지 되돌리기 가능",
            row.RollbackAvailabilityLabel);
        Assert.IsTrue(row.CanRollback);
    }

    [TestMethod]
    public void ReceiptWithoutValidExpiry_CannotOfferRollback()
    {
        // Given
        var missing = new PanelItemPresentation(
            "approval-missing-expiry",
            "approval",
            "Missing expiry",
            ReceiptRef: "office:job-missing");
        var invalid = new PanelItemPresentation(
            "approval-invalid-expiry",
            "approval",
            "Invalid expiry",
            ExpiresAt: "not-a-timestamp",
            ReceiptRef: "office:job-invalid");

        // Then
        Assert.IsFalse(missing.CanRollback);
        Assert.IsFalse(invalid.CanRollback);
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

    private static NativeProjectionState ReceiptProjection()
    {
        const string instanceId = "0123456789abcdef0123456789abcdef";
        var body = new NativeJsonObject([
            new("protocol_version", new NativeJsonInteger(1)),
            new("session_id", new NativeJsonString("session-receipt")),
            new("cursor", new NativeJsonInteger(7)),
            new("panels", new NativeJsonArray([
                new NativeJsonObject([
                    new("key", new NativeJsonString("approvals")),
                    new("items", new NativeJsonArray([
                        new NativeJsonObject([
                            new("id", new NativeJsonString("approval-7")),
                            new("kind", new NativeJsonString("approval")),
                            new("summary", new NativeJsonString("Office export completed")),
                            new("status", new NativeJsonString("approved")),
                            new("ui_state", new NativeJsonString("succeeded")),
                            new("cursor", new NativeJsonInteger(7)),
                            new("destination", new NativeJsonString("C:\\workspace\\approved.xlsx")),
                            new("expires_at", new NativeJsonString("2099-09-28T12:00:00+00:00")),
                            new("receipt_ref", new NativeJsonString("office:job-7")),
                            new("backup_exists", new NativeJsonBoolean(true)),
                        ]),
                    ])),
                ]),
            ])),
            new("conversation", new NativeJsonArray([])),
            new("composer", new NativeJsonObject([])),
            new("status", new NativeJsonObject([])),
            new("working_memory", new NativeJsonObject([])),
            new("approval_policy", new NativeJsonObject([])),
            new("terminals", new NativeJsonArray([])),
            new("instance_id", new NativeJsonString(instanceId)),
            new("reset_reason", new NativeJsonString("initial")),
        ]);
        var store = new NativeProjectionStore();
        store.ApplySnapshot(
            new NativeEnvelope(
                NativeMessageKind.Snapshot,
                "snapshot-receipt",
                body),
            new NativeReadyIdentity("session-receipt", instanceId, "test"));
        return store.State!;
    }

    private static NativeEnvelope Decode(JsonElement vector) => NativeFrameCodec.Decode(
        Convert.FromBase64String(vector.GetProperty("frame_base64").GetString()!));
}
