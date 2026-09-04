using System.IO;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Support;

[TestClass]
public sealed class BridgeProcessHarnessTests
{
    [TestMethod]
    public void CreateStartInfo_PreparesExactReceiptParentAndUsesLockedRepositoryPython()
    {
        // Given
        var temporaryRoot = Path.Combine(
            Path.GetTempPath(),
            $"birkin-harness-root-test-{Guid.NewGuid():N}");
        var bridgeRoot = Path.Combine(temporaryRoot, "workspace");
        Directory.CreateDirectory(bridgeRoot);

        try
        {
            // When
            var start = BridgeProcessHarness.CreateStartInfo(bridgeRoot);

            // Then
            StringAssert.EndsWith(
                start.FileName,
                Path.Combine(".venv", "Scripts", "python.exe"));
            CollectionAssert.AreEqual(
                new[]
                {
                    "-m", "birkin.native.serve",
                    "--transport", "loopback",
                    "--root", bridgeRoot,
                },
                start.ArgumentList.ToArray());
            Assert.AreEqual(
                Path.Combine(temporaryRoot, "home"),
                start.Environment["BIRKIN_HOME"]);
            Assert.IsTrue(Directory.Exists(Path.Combine(
                bridgeRoot,
                "workspace",
                "native-app",
                "receipts")));
        }
        finally
        {
            Directory.Delete(temporaryRoot, recursive: true);
        }
    }

    [TestMethod]
    public async Task StopOwnedProcessAsync_WhenOwnedProcessExitsBeforeKill_TreatsObservedExitAsSuccess()
    {
        // Given
        var process = new RaceOwnedBridgeProcess(exitsBeforeKill: true);

        // When
        await BridgeProcessHarness.StopOwnedProcessAsync(process);

        // Then
        CollectionAssert.AreEqual(
            new[] { "HasExited:false", "KillEntireProcessTree", "HasExited:true", "WaitForExitAsync" },
            process.Calls);
    }

    [TestMethod]
    public async Task StopOwnedProcessAsync_WhenKillFailsWhileOwnedProcessIsRunning_LeavesFailureLoud()
    {
        // Given
        var process = new RaceOwnedBridgeProcess(exitsBeforeKill: false);

        // When
        await Assert.ThrowsExceptionAsync<InvalidOperationException>(
            () => BridgeProcessHarness.StopOwnedProcessAsync(process));

        // Then
        CollectionAssert.AreEqual(
            new[] { "HasExited:false", "KillEntireProcessTree", "HasExited:false" },
            process.Calls);
    }

    private sealed class RaceOwnedBridgeProcess : IOwnedBridgeProcess
    {
        private readonly bool _exitsBeforeKill;
        private bool _hasExited;

        public RaceOwnedBridgeProcess(bool exitsBeforeKill) => _exitsBeforeKill = exitsBeforeKill;

        public List<string> Calls { get; } = [];

        public int Id => 7228;

        public bool HasExited
        {
            get
            {
                Calls.Add($"HasExited:{_hasExited.ToString().ToLowerInvariant()}");
                return _hasExited;
            }
        }

        public void KillEntireProcessTree()
        {
            Calls.Add("KillEntireProcessTree");
            _hasExited = _exitsBeforeKill;
            throw new InvalidOperationException("Process has exited.");
        }

        public Task WaitForExitAsync()
        {
            Calls.Add("WaitForExitAsync");
            return Task.CompletedTask;
        }

        public void Dispose() => Calls.Add("Dispose");
    }
}
