using System.IO;
using Birkin.Native.App.Startup;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Journeys;

[TestClass]
public sealed class LiveBridgeIntegrationTests
{
    [TestMethod]
    [TestCategory("LiveBridge")]
    public async Task ReceivesPostSnapshotUpdate_WhenRealLoopbackBridgeIsServing()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        await using var bridge = await BridgeProcessHarness.StartAsync(deadline.Token);
        var announcementJson = await bridge.WaitForListeningAsync(deadline.Token);
        var announcementFile = Path.Combine(bridge.TemporaryRoot, "announcement.jsonl");
        await File.WriteAllTextAsync(announcementFile, announcementJson + Environment.NewLine, deadline.Token);
        var options = AppOptions.Parse(["--bridge-announcement-file", announcementFile]);
        var announcement = BridgeAnnouncement.Parse(options.BridgeAnnouncementJson);
        await using var composition = CompositionRoot.Create(new ImmediateSynchronizationContext());
        var applied = new TaskCompletionSource<WorkspaceSnapshotPresentation>(TaskCreationOptions.RunContinuationsAsynchronously);
        composition.Coordinator.SnapshotApplied += snapshot => applied.TrySetResult(snapshot);
        await composition.Runner.RunAsync(options, deadline.Token);
        var snapshot = await applied.Task.WaitAsync(deadline.Token);
        var updated = new TaskCompletionSource<WorkspaceSnapshotPresentation>(TaskCreationOptions.RunContinuationsAsynchronously);
        composition.PresentationModel.PropertyChanged += (_, args) =>
        {
            var workspace = composition.PresentationModel.Workspace;
            if (args.PropertyName == nameof(ShellPresentationModel.Workspace)
                && workspace is not null
                && workspace.Cursor > snapshot.Cursor)
            {
                updated.TrySetResult(workspace);
            }
        };
        var failed = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        composition.Coordinator.ConnectionStateChanged += state =>
        {
            if (state == ConnectionState.Failed)
            {
                failed.TrySetResult(composition.PresentationModel.Connection.ErrorCode ?? "E_CONNECTION");
            }
        };
        var request = new NativeCommandRequest(
            new NativeCommandIdentity("windows-live-session-rename", snapshot.Cursor),
            new NativeCommandIntent(
                "session.rename",
                new NativeJsonObject([
                    new("session_id", new NativeJsonString(snapshot.SessionId)),
                    new("name", new NativeJsonString("Windows live loopback")),
                ])),
            "window-main");

        // When
        _ = await composition.Session.SendCommandForResultAsync(request, deadline.Token);
        var completed = await Task.WhenAny(updated.Task, failed.Task).WaitAsync(deadline.Token);
        if (completed == failed.Task)
        {
            throw new AssertFailedException($"Live receive failed with {await failed.Task}.");
        }
        var live = await updated.Task.WaitAsync(deadline.Token);

        // Then
        Assert.AreEqual(ConnectionState.Ready, composition.PresentationModel.Connection.State);
        var current = composition.PresentationModel.Workspace;
        Assert.IsNotNull(current);
        Assert.IsTrue(current.Cursor >= live.Cursor);
        Assert.IsFalse(options.BridgeAnnouncementJson.Contains("\"bootstrap_secret\"", StringComparison.Ordinal));
        Assert.AreEqual(1L, live.ProtocolVersion);
        Assert.AreEqual(announcement.SessionId, live.SessionId);
        Assert.AreEqual(announcement.InstanceId, live.InstanceId);
        Assert.AreEqual("loopback", live.Transport);
        Assert.IsTrue(live.Cursor > snapshot.Cursor);
        Assert.AreEqual("initial", live.ResetReason);
        Assert.IsTrue(live.PanelCount > 0);
        Assert.AreEqual(string.Empty, bridge.StandardError, bridge.StandardError);
        Console.WriteLine($"ANNOUNCEMENT={announcementJson}");
        Console.WriteLine("ANNOUNCEMENT_HAS_BOOTSTRAP_SECRET=false");
        Console.WriteLine($"READY=protocol_version={snapshot.ProtocolVersion};server_version={announcement.ServerVersion};instance_id={snapshot.InstanceId};capability=[REDACTED]");
        Console.WriteLine($"PYTHON_SNAPSHOT=session_id={snapshot.SessionId};cursor={snapshot.Cursor};instance_id={snapshot.InstanceId};reset_reason={snapshot.ResetReason};transport={snapshot.Transport};panel_count={snapshot.PanelCount}");
        Console.WriteLine($"POST_SNAPSHOT_UI=initial_cursor={snapshot.Cursor};first_live_cursor={live.Cursor};current_cursor={current.Cursor}");
        Console.WriteLine("BRIDGE_STDERR_EMPTY=true");
        Console.WriteLine($"LAUNCHER_DIAGNOSTICS={bridge.LauncherDiagnostics}");
        Console.WriteLine($"BRIDGE_PID={bridge.ProcessId}");
    }

    private sealed class ImmediateSynchronizationContext : SynchronizationContext
    {
        public override void Post(SendOrPostCallback callback, object? state) => callback(state);
    }
}
