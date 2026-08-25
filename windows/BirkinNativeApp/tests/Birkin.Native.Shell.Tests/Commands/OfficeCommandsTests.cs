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
}
