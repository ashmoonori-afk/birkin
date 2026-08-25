using System.IO;
using System.Text;
using Birkin.Native.App.Startup;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Journeys;

[TestClass]
public sealed class ProviderOfficeDeterministicSeamTests
{
    [TestMethod]
    [TestCategory("OfficeWorkflow")]
    [TestCategory("DeterministicWindow")]
    public async Task ProductionMainWindow_ExposesEntireOfficeJourneyWithoutInvokingProvider()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(90));
        var repositoryRoot = FindRepositoryRoot();
        var evidenceRoot = Path.Combine(
            repositoryRoot, ".omo", "evidence", "native-windows-20260824", "final-review-fixes", "g");
        if (Directory.Exists(evidenceRoot))
        {
            Directory.Delete(evidenceRoot, recursive: true);
        }
        var evidence = new ProviderOfficeEvidence(evidenceRoot);
        var bridge = await BridgeProcessHarness.StartAsync(deadline.Token);
        await using (bridge)
        {
            var announcementJson = await bridge.WaitForListeningAsync(deadline.Token);
            var announcementFile = Path.Combine(bridge.TemporaryRoot, "announcement.jsonl");
            await File.WriteAllTextAsync(announcementFile, announcementJson + Environment.NewLine, deadline.Token);
            var options = AppOptions.Parse(["--bridge-announcement-file", announcementFile]);
            _ = BridgeAnnouncement.Parse(options.BridgeAnnouncementJson);
            await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
            var journey = await sta.InvokeAsync(async () =>
            {
                await using var composition = CompositionRoot.Create(
                    SynchronizationContext.Current
                    ?? throw new InvalidOperationException("WPF dispatcher synchronization context is unavailable"));
                var initial = new TaskCompletionSource<WorkspaceSnapshotPresentation>(TaskCreationOptions.RunContinuationsAsynchronously);
                composition.Coordinator.SnapshotApplied += InitialApplied;
                try
                {
                    await composition.Runner.RunAsync(options, deadline.Token);
                    _ = await initial.Task.WaitAsync(deadline.Token);
                    Assert.AreEqual(ConnectionState.Ready, composition.PresentationModel.Connection.State);
                    var result = await ProviderOfficeJourneyFlow.RunAsync(
                        repositoryRoot,
                        bridge.TemporaryRoot,
                        composition,
                        evidence,
                        evidenceRoot,
                        invokeProvider: false,
                        deadline.Token);
                    Assert.AreEqual(0, result.ProviderInvocations);
                    Assert.AreEqual(1, composition.Session.MaximumConcurrentReceives);
                }
                finally
                {
                    composition.Coordinator.SnapshotApplied -= InitialApplied;
                }

                void InitialApplied(WorkspaceSnapshotPresentation snapshot) => initial.TrySetResult(snapshot);
            });
            await journey.WaitAsync(deadline.Token);
            evidence.CaptureWorkspace(bridge.TemporaryRoot);
            var diagnostic = File.ReadAllText(evidence.DiagnosticPath);
            Assert.IsFalse(diagnostic.Contains("provider-turn", StringComparison.Ordinal));
            Assert.IsFalse(diagnostic.Contains("provider-assistant", StringComparison.Ordinal));
            Assert.AreEqual(0, Encoding.UTF8.GetByteCount(bridge.StandardError));
        }

        Assert.IsTrue(bridge.OwnedProcessExited);
        Assert.IsTrue(bridge.TemporaryRootDeleted);
        evidence.Record("cleanup", new Dictionary<string, object?>
        {
            ["owned_process_exited"] = bridge.OwnedProcessExited,
            ["temporary_root_deleted"] = bridge.TemporaryRootDeleted,
        });
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "pyproject.toml")))
        {
            directory = directory.Parent;
        }
        return directory?.FullName ?? throw new InvalidOperationException("repository root was not found");
    }
}
