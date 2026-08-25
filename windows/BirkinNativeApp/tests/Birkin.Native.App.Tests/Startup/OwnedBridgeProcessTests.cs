using Birkin.Native.App.Startup;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Startup;

[TestClass]
public sealed class OwnedBridgeProcessTests
{
    [TestMethod]
    public async Task StopAsync_WhenCloseMainWindowIsImpossible_KillsEntireTreeBeforeAwaitingExit()
    {
        var calls = new List<string>();

        await OwnedBridgeProcess.StopAsync(
            () =>
            {
                calls.Add("close");
                return false;
            },
            () => false,
            () => calls.Add("kill-tree"),
            _ =>
            {
                calls.Add("wait-async");
                return Task.CompletedTask;
            },
            TimeSpan.FromSeconds(5),
            CancellationToken.None);

        CollectionAssert.AreEqual(new[] { "close", "kill-tree", "wait-async" }, calls);
    }

    [TestMethod]
    public async Task StopAsync_WhenOrderlyExitCompletes_DoesNotKillProcess()
    {
        var calls = new List<string>();

        await OwnedBridgeProcess.StopAsync(
            () =>
            {
                calls.Add("close");
                return true;
            },
            () => false,
            () => calls.Add("kill-tree"),
            _ =>
            {
                calls.Add("wait-async");
                return Task.CompletedTask;
            },
            TimeSpan.FromSeconds(5),
            CancellationToken.None);

        CollectionAssert.AreEqual(new[] { "close", "wait-async" }, calls);
    }
}
