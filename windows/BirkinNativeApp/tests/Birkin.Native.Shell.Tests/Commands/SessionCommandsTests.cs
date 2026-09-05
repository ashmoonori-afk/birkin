using Birkin.Native.Protocol.Framing;
using Birkin.Native.Shell.Commands;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Commands;

[TestClass]
public sealed class SessionCommandsTests
{
    private static readonly CommandRequestContext Context = new("session-command-1", 12, "office");

    [TestMethod]
    public void LifecycleCommands_BuildExactPythonPayloads()
    {
        var create = SessionCommands.Create("weekly", Context);
        var select = SessionCommands.Select("weekly", Context);
        var rename = SessionCommands.Rename("weekly", "주간 보고", Context);

        Assert.AreEqual("session.create", create.CommandType);
        Assert.AreEqual("session.select", select.CommandType);
        Assert.AreEqual("session.rename", rename.CommandType);
        Assert.AreEqual("weekly", ((NativeJsonString)create.Payload["session_id"]!).Value);
        Assert.AreEqual("주간 보고", ((NativeJsonString)rename.Payload["name"]!).Value);
    }
}
