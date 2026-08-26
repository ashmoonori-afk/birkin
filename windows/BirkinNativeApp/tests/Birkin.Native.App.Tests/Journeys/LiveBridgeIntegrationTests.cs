using System.IO;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using Birkin.Native.App.Startup;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Journeys;

[TestClass]
public sealed partial class LiveBridgeIntegrationTests
{
    [TestMethod]
    [TestCategory("LiveBridge")]
    public async Task ConnectsAndReceivesPythonSnapshot_WhenRealLoopbackBridgeIsServing()
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

        // When
        await composition.Runner.RunAsync(options, deadline.Token);
        var snapshot = await applied.Task.WaitAsync(deadline.Token);

        // Then
        Assert.AreEqual(ConnectionState.Ready, composition.PresentationModel.Connection.State);
        Assert.AreSame(snapshot, composition.PresentationModel.Workspace);
        Assert.IsFalse(options.BridgeAnnouncementJson.Contains("\"bootstrap_secret\"", StringComparison.Ordinal));
        Assert.AreEqual(1L, snapshot.ProtocolVersion);
        Assert.AreEqual(announcement.SessionId, snapshot.SessionId);
        Assert.AreEqual(announcement.InstanceId, snapshot.InstanceId);
        Assert.AreEqual("loopback", snapshot.Transport);
        Assert.IsTrue(snapshot.Cursor >= 0);
        Assert.AreEqual("initial", snapshot.ResetReason);
        Assert.IsTrue(snapshot.PanelCount > 0);
        Assert.AreEqual(string.Empty, bridge.StandardError, bridge.StandardError);
        Console.WriteLine($"ANNOUNCEMENT={announcementJson}");
        Console.WriteLine("ANNOUNCEMENT_HAS_BOOTSTRAP_SECRET=false");
        Console.WriteLine($"READY=protocol_version={snapshot.ProtocolVersion};server_version={announcement.ServerVersion};instance_id={snapshot.InstanceId};capability=[REDACTED]");
        Console.WriteLine($"PYTHON_SNAPSHOT=session_id={snapshot.SessionId};cursor={snapshot.Cursor};instance_id={snapshot.InstanceId};reset_reason={snapshot.ResetReason};transport={snapshot.Transport};panel_count={snapshot.PanelCount}");
        Console.WriteLine("BRIDGE_STDERR_EMPTY=true");
        Console.WriteLine($"LAUNCHER_DIAGNOSTICS={bridge.LauncherDiagnostics}");
        Console.WriteLine($"BRIDGE_PID={bridge.ProcessId}");
    }

}
