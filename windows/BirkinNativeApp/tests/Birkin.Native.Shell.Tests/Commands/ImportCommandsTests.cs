using Birkin.Native.Protocol.Framing;
using Birkin.Native.Shell.Commands;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Commands;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class ImportCommandsTests
{
    [TestMethod]
    public void Import_WhenSourceSelected_BuildsPythonJailedCopyIntent()
    {
        // Given
        var context = new CommandRequestContext("import-command-1", 7, "imports");

        // When
        var request = ImportCommands.Import(new FileImportIntent(@"C:\Users\me\report.xlsx"), context);

        // Then
        Assert.AreEqual("file.import", request.CommandType);
        Assert.AreEqual(1, request.Payload.Count);
        Assert.AreEqual(@"C:\Users\me\report.xlsx", ((NativeJsonString)request.Payload["source_path"]!).Value);
    }
}
