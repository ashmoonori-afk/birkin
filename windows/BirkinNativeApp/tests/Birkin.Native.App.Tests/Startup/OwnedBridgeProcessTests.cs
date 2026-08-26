using System.Diagnostics;
using System.Reflection;
using Birkin.Native.App.Startup;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Startup;

[TestClass]
public sealed class OwnedBridgeProcessTests
{
    [TestMethod]
    public void CreateStartInfo_WhenPythonModulePrefixIsConfigured_LaunchesDirectlyWithoutAConsole()
    {
        // Given
        var processType = typeof(AppOptions).Assembly.GetType("Birkin.Native.App.Startup.OwnedBridgeProcess");
        var factory = processType?.GetMethod("CreateStartInfo", BindingFlags.Static | BindingFlags.NonPublic);

        // When
        var start = factory?.Invoke(null, [@"C:\repo\.venv\Scripts\python.exe", "-m birkin"])
            as ProcessStartInfo;

        // Then
        Assert.IsNotNull(start, "owned bridge start-info factory is unavailable");
        Assert.AreEqual(@"C:\repo\.venv\Scripts\python.exe", start.FileName);
        Assert.AreEqual("-m birkin native-bridge serve --transport loopback", start.Arguments);
        Assert.IsTrue(start.CreateNoWindow);
        Assert.IsFalse(start.UseShellExecute);
        Assert.IsTrue(start.RedirectStandardOutput);
    }
}
