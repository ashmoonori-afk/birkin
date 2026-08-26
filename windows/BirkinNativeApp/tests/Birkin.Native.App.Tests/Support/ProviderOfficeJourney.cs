using System.IO;
using System.Text;
using Birkin.Native.App.Startup;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Support;

internal static class ProviderOfficeJourney
{
    public static async Task RunAsync()
    {
        var repositoryRoot = FindRepositoryRoot();
        var evidenceRoot = Path.Combine(
            repositoryRoot, ".omo", "evidence", "native-windows-20260824", "remediation", "w6");
        var evidence = new ProviderOfficeEvidence(evidenceRoot);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(240));
        var bridge = await BridgeProcessHarness.StartAsync(deadline.Token);
        await using (bridge)
        {
            var announcementJson = await bridge.WaitForListeningAsync(deadline.Token);
            var announcementFile = Path.Combine(bridge.TemporaryRoot, "announcement.jsonl");
            await File.WriteAllTextAsync(announcementFile, announcementJson + Environment.NewLine, deadline.Token);
            var options = AppOptions.Parse(["--bridge-announcement-file", announcementFile]);
            var announcement = BridgeAnnouncement.Parse(options.BridgeAnnouncementJson);
            evidence.Record("bridge-listening", new Dictionary<string, object?>
            {
                ["pid"] = bridge.ProcessId,
                ["session_id"] = announcement.SessionId,
                ["instance_id"] = announcement.InstanceId,
            });

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
                    var ready = await initial.Task.WaitAsync(deadline.Token);
                    Assert.AreEqual(ConnectionState.Ready, composition.PresentationModel.Connection.State);
                    Assert.IsTrue(composition.Session.OwnsReceiveLoop);
                    Assert.AreEqual(1, composition.Session.MaximumConcurrentReceives);
                    Assert.IsTrue(composition.Session.AdvertisedCommands.Contains("chat.send"));
                    Assert.IsTrue(composition.Session.AdvertisedCommands.Contains("office.compare"));
                    Assert.IsTrue(composition.Session.AdvertisedCommands.Contains("office.draft"));
                    evidence.Record("ready", new Dictionary<string, object?>
                    {
                        ["cursor"] = ready.Cursor,
                        ["session_id"] = ready.SessionId,
                        ["instance_id"] = ready.InstanceId,
                    });

                    var result = await ProviderOfficeJourneyFlow.RunAsync(
                        repositoryRoot,
                        bridge.TemporaryRoot,
                        composition,
                        evidence,
                        evidenceRoot,
                        invokeProvider: true,
                        deadline.Token);
                    Assert.AreEqual(1, result.ProviderInvocations);
                    evidence.Record("provider-invoked", new Dictionary<string, object?>
                    {
                        ["provider_invocations"] = result.ProviderInvocations,
                    });
                    Assert.AreEqual(1, composition.Session.MaximumConcurrentReceives);
                }
                finally
                {
                    composition.Coordinator.SnapshotApplied -= InitialApplied;
                }

                void InitialApplied(WorkspaceSnapshotPresentation snapshot) => initial.TrySetResult(snapshot);
            });

            try
            {
                await journey.WaitAsync(deadline.Token);
                evidence.CaptureWorkspace(bridge.TemporaryRoot);
            }
            catch
            {
                evidence.Record("failure-diagnostics", new Dictionary<string, object?>
                {
                    ["stderr_bytes"] = Encoding.UTF8.GetByteCount(bridge.StandardError),
                    ["stderr_sha256"] = ProviderOfficeEvidence.Hash(bridge.StandardError),
                    ["launcher_diagnostics_bytes"] = Encoding.UTF8.GetByteCount(bridge.LauncherDiagnostics),
                    ["launcher_diagnostics_sha256"] = ProviderOfficeEvidence.Hash(bridge.LauncherDiagnostics),
                });
                evidence.CaptureWorkspace(bridge.TemporaryRoot);
                throw;
            }

            Assert.AreEqual(0, Encoding.UTF8.GetByteCount(bridge.StandardError),
                "bridge stderr was non-empty; content was retained only as redacted diagnostics");
        }

        Assert.IsTrue(bridge.OwnedProcessExited, "the exact owned bridge Process did not exit");
        Assert.IsTrue(bridge.TemporaryRootDeleted, "the exact owned temporary root was not deleted");
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
