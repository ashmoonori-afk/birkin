using Birkin.Native.Protocol.Framing;
using Birkin.Native.Shell.Commands;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Commands;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class OfficeCommandsTests
{
    private static readonly CommandRequestContext Context = new("office-command-1", 19, "office");
    private static readonly OfficeArtifact Artifact = new(
        "artifact:1", "sha256", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "file:///workspace/drafts/report.docx", "private", "acl");

    [TestMethod]
    public void Create_WhenFormIsComplete_BuildsExactPythonPayload()
    {
        // Given / When
        var request = OfficeCommands.Create(
            new OfficeCreateIntent("docx", new OfficeDocumentContent(["Report"]), "report.docx"), Context);

        // Then
        Assert.AreEqual("office.create", request.CommandType);
        CollectionAssert.AreEquivalent(new[] { "format", "content", "output_name" }, request.Payload.Keys.ToArray());
        var content = (NativeJsonObject)request.Payload["content"]!;
        Assert.AreEqual("Report", ((NativeJsonString)((NativeJsonArray)content["paragraphs"]!).Values[0]).Value);
    }

    [TestMethod]
    public void SelectAndOpen_WhenArtifactKnown_BuildExactPythonPayloads()
    {
        // Given / When
        var select = OfficeCommands.Select(new OfficeSelectIntent("artifact:1"), Context);
        var open = OfficeCommands.Open(new OfficeOpenIntent(Artifact), Context);

        // Then
        Assert.AreEqual("office.select", select.CommandType);
        Assert.AreEqual("artifact:1", ((NativeJsonString)select.Payload["artifact_id"]!).Value);
        Assert.AreEqual("office.open", open.CommandType);
        Assert.AreEqual(6, ((NativeJsonObject)open.Payload["artifact"]!).Count);
    }

    [TestMethod]
    public void Convert_WhenPlanGiven_BuildsExactPythonPayload()
    {
        // Given / When
        var request = OfficeCommands.Convert(
            new OfficeConvertIntent(Artifact, "txt", "report.txt", OfficeLossBudget.Zero), Context);

        // Then
        Assert.AreEqual("office.convert", request.CommandType);
        CollectionAssert.AreEquivalent(
            new[] { "artifact", "target_format", "output_name", "loss_budget" }, request.Payload.Keys.ToArray());
        Assert.AreEqual(10, ((NativeJsonObject)request.Payload["loss_budget"]!).Count);
    }

    [TestMethod]
    public void Draft_WhenCreationPlanGiven_BuildsOfficeJobRequestPayload()
    {
        // Given / When
        var request = OfficeCommands.Draft(
            new OfficeDraftIntent(
                "Create the quarterly report",
                "docx",
                new OfficeDocumentContent(["Quarterly report", "Revenue increased."]),
                "Create a new quarterly report",
                "quarterly-report.docx",
                false),
            Context);

        // Then
        Assert.AreEqual("office.job_request", request.CommandType);
        CollectionAssert.AreEquivalent(
            new[] { "request", "format", "content", "outcome", "destination", "overwrite_approved" },
            request.Payload.Keys.ToArray());
        var content = (NativeJsonObject)request.Payload["content"]!;
        var paragraphs = (NativeJsonArray)content["paragraphs"]!;
        Assert.AreEqual("Quarterly report", ((NativeJsonString)paragraphs.Values[0]).Value);
        Assert.AreEqual("Revenue increased.", ((NativeJsonString)paragraphs.Values[1]).Value);
        Assert.AreEqual("quarterly-report.docx", ((NativeJsonString)request.Payload["destination"]!).Value);
        Assert.IsFalse(((NativeJsonBoolean)request.Payload["overwrite_approved"]!).Value);
    }

    [TestMethod]
    public void RollbackRequest_WhenReceiptKnown_HidesInternalJobIdentifier()
    {
        // Given / When
        var request = OfficeCommands.RollbackRequest(
            new OfficeRollbackRequestIntent("office:job-7"),
            Context);

        // Then
        Assert.AreEqual("office.rollback_request", request.CommandType);
        CollectionAssert.AreEquivalent(
            new[] { "receipt_ref" },
            request.Payload.Keys.ToArray());
        Assert.AreEqual(
            "office:job-7",
            ((NativeJsonString)request.Payload["receipt_ref"]!).Value);
        Assert.IsFalse(request.Payload.ContainsKey("job_id"));
    }
}
