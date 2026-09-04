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
    public async Task DisposeAsync_WhenOwnedRootContainsNestedReadOnlyFile_RemovesOwnedRootWithoutThrowing()
    {
        // Given
        var temporaryRoot = Path.Combine(
            Path.GetTempPath(),
            $"birkin-harness-dispose-test-{Guid.NewGuid():N}");
        var readOnlyFile = Path.Combine(
            temporaryRoot,
            "checkpoints",
            "store",
            "objects",
            "00",
            "object");
        Directory.CreateDirectory(Path.GetDirectoryName(readOnlyFile)!);
        File.WriteAllText(readOnlyFile, "fixture");
        File.SetAttributes(readOnlyFile, File.GetAttributes(readOnlyFile) | FileAttributes.ReadOnly);
        var harness = new BridgeProcessHarness(
            new ExitedOwnedBridgeProcess(),
            temporaryRoot,
            new TaskCompletionSource<string>(),
            new BridgeStandardErrorCapture());

        try
        {
            // When
            await harness.DisposeAsync();

            // Then
            Assert.IsFalse(Directory.Exists(temporaryRoot));
            Assert.IsTrue(harness.TemporaryRootDeleted);
        }
        finally
        {
            if (File.Exists(readOnlyFile))
            {
                File.SetAttributes(readOnlyFile, FileAttributes.Normal);
            }
            if (Directory.Exists(temporaryRoot))
            {
                Directory.Delete(temporaryRoot, recursive: true);
            }
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

    private sealed class ExitedOwnedBridgeProcess : IOwnedBridgeProcess
    {
        public int Id => 7228;

        public bool HasExited => true;

        public void KillEntireProcessTree() => throw new InvalidOperationException("already exited");

        public Task WaitForExitAsync() => Task.CompletedTask;

        public void Dispose()
        {
        }
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
