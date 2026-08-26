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

public sealed partial class LiveBridgeIntegrationTests
{
    [TestMethod]
    [TestCategory("LiveBridge")]
    [TestCategory("Terminal")]
    public async Task TerminalControls_WhenAuthenticatedProviderFreeBridgeIsReady_DriveCanonicalConPtyJourney()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(60));
        var bridge = await BridgeProcessHarness.StartAsync(deadline.Token, providerFree: true);
        var bridgePid = bridge.ProcessId;
        var hiddenBridge = !TerminalRedEvidenceCapture.HasConsoleWindow(bridgePid);
        var missingControls = new List<string>();
        var subscriptions = new[] { "UIA.WindowOpened", "terminal.opened", "terminal.output", "terminal.exited" };
        string bridgeError = string.Empty;
        var liveStage = "bridge-started";

        await using (bridge)
        {
            var announcementJson = await bridge.WaitForListeningAsync(deadline.Token);
            var announcementFile = Path.Combine(bridge.TemporaryRoot, "announcement.jsonl");
            await File.WriteAllTextAsync(announcementFile, announcementJson + Environment.NewLine, deadline.Token);
            var options = AppOptions.Parse(["--bridge-announcement-file", announcementFile]);
            var announcement = BridgeAnnouncement.Parse(options.BridgeAnnouncementJson);
            await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
            var journey = await sta.InvokeAsync(async () =>
            {
                await using var composition = CompositionRoot.Create(
                    SynchronizationContext.Current
                    ?? throw new InvalidOperationException("WPF dispatcher synchronization context is unavailable"));
                var initial = new TaskCompletionSource<WorkspaceSnapshotPresentation>(TaskCreationOptions.RunContinuationsAsynchronously);
                var terminalOpened = new TaskCompletionSource<NativeEnvelope>(TaskCreationOptions.RunContinuationsAsynchronously);
                var terminalOutput = new TaskCompletionSource<WorkspaceSnapshotPresentation>(TaskCreationOptions.RunContinuationsAsynchronously);
                var terminalExited = new TaskCompletionSource<NativeEnvelope>(TaskCreationOptions.RunContinuationsAsynchronously);
                var inputTriggered = false;
                composition.Coordinator.SnapshotApplied += InitialApplied;
                composition.Coordinator.SnapshotApplied += TerminalDisplayApplied;
                composition.ProjectionStore.CanonicalApplied += TerminalApplied;
                composition.PresentationModel.PropertyChanged += PresentationChanged;
                try
                {
                    await composition.Runner.RunAsync(options, deadline.Token);
                    _ = await initial.Task.WaitAsync(deadline.Token);
                    liveStage = "snapshot-ready";
                    Assert.IsTrue(composition.Session.AdvertisedCommands.Contains("terminal.create"),
                        "the authenticated Windows bridge did not advertise terminal.create");

                    var uiOpened = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                    AutomationEventHandler openedHandler = (sender, _) =>
                    {
                        if (sender is AutomationElement element && element.Current.ProcessId == Environment.ProcessId)
                        {
                            uiOpened.TrySetResult(true);
                        }
                    };
                    Automation.AddAutomationEventHandler(
                        WindowPattern.WindowOpenedEvent,
                        AutomationElement.RootElement,
                        TreeScope.Children,
                        openedHandler);
                    var window = new MainWindow(composition.PresentationModel, composition.Coordinator)
                    {
                        Width = 1500,
                        Height = 940,
                        WindowStartupLocation = WindowStartupLocation.Manual,
                        Left = 0,
                        Top = 0,
                    };
                    try
                    {
                        window.Show();
                        await uiOpened.Task.WaitAsync(deadline.Token);
                        await window.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.Render);
                        foreach (var id in new[] { "terminal.create", "terminal.input", "terminal.output" })
                        {
                            if (OfficeWorkflowViewHarness.FindAll<FrameworkElement>(window, id).Count == 0)
                            {
                                missingControls.Add(id);
                            }
                        }

                        TerminalRedEvidenceCapture.CaptureWindow(window, 1500, 940);
                        TerminalRedEvidenceCapture.CaptureWindow(window, 1100, 700);
                        TerminalRedEvidenceCapture.CaptureUiaTree(window);

                        if (missingControls.Count == 0)
                        {
                            OfficeWorkflowViewHarness.Find<Button>(window, "terminal.create")
                                .RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                            liveStage = "create-invoked";
                            var opened = await terminalOpened.Task.WaitAsync(deadline.Token);
                            liveStage = "terminal-opened";
                            var openedPayload = opened.Body["payload"] as NativeJsonObject
                                ?? throw new AssertFailedException("terminal.opened payload was not an object");
                            var openedCwd = openedPayload["cwd"] as NativeJsonString
                                ?? throw new AssertFailedException("terminal.opened cwd was not a string");
                            Assert.AreEqual(announcement.Root, openedCwd.Value);
                            var input = OfficeWorkflowViewHarness.Find<TextBox>(window, "terminal.input");
                            input.Text = "echo CONPTY_OK";
                            OfficeWorkflowViewHarness.Find<Button>(window, "terminal.send")
                                .RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                            liveStage = "input-invoked";
                            inputTriggered = true;
                            _ = await terminalOutput.Task.WaitAsync(deadline.Token);
                            liveStage = "terminal-output";
                            OfficeWorkflowViewHarness.Find<Button>(window, "terminal.close")
                                .RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                            liveStage = "close-invoked";
                            _ = await terminalExited.Task.WaitAsync(deadline.Token);
                            liveStage = "terminal-exited";
                        }
                    }
                    finally
                    {
                        Automation.RemoveAutomationEventHandler(
                            WindowPattern.WindowOpenedEvent,
                            AutomationElement.RootElement,
                            openedHandler);
                        window.Close();
                    }
                }
                finally
                {
                    composition.Coordinator.SnapshotApplied -= InitialApplied;
                    composition.Coordinator.SnapshotApplied -= TerminalDisplayApplied;
                    composition.ProjectionStore.CanonicalApplied -= TerminalApplied;
                    composition.PresentationModel.PropertyChanged -= PresentationChanged;
                }

                void PresentationChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs eventArgs)
                {
                    if (inputTriggered && eventArgs.PropertyName == nameof(ShellPresentationModel.TerminalWorkflow))
                    {
                        liveStage = $"input-{composition.PresentationModel.TerminalWorkflow.CommandState}-{composition.PresentationModel.TerminalWorkflow.UserFacingFailure}";
                    }
                }
                void InitialApplied(WorkspaceSnapshotPresentation snapshot) => initial.TrySetResult(snapshot);
                void TerminalDisplayApplied(WorkspaceSnapshotPresentation snapshot)
                {
                    if (snapshot.Terminal.Display.Contains("CONPTY_OK", StringComparison.Ordinal))
                    {
                        terminalOutput.TrySetResult(snapshot);
                    }
                }
                void TerminalApplied(NativeEnvelope envelope)
                {
                    if (envelope.Kind != NativeMessageKind.Event
                        || envelope.Body["type"] is not NativeJsonString type)
                    {
                        return;
                    }
                    if (type.Value == "terminal.opened")
                    {
                        terminalOpened.TrySetResult(envelope);
                    }
                    else if (type.Value == "terminal.exited")
                    {
                        terminalExited.TrySetResult(envelope);
                    }
                }
            });
            try
            {
                await journey.WaitAsync(deadline.Token);
            }
            catch (OperationCanceledException)
            {
                Assert.Fail($"Live terminal journey timed out at stage: {liveStage}");
            }
            bridgeError = bridge.StandardError;
        }

        TerminalRedEvidenceCapture.WriteJourneyReceipt(
            bridgePid,
            hiddenBridge,
            bridge.OwnedProcessExited,
            bridge.TemporaryRootDeleted,
            subscriptions,
            missingControls);
        Assert.IsTrue(hiddenBridge, "owned bridge exposed a console window");
        Assert.IsTrue(bridge.OwnedProcessExited, "exact owned bridge process survived cleanup");
        Assert.IsTrue(bridge.TemporaryRootDeleted, "secret-bearing QA root survived cleanup");
        Assert.AreEqual(string.Empty, bridgeError, bridgeError);
        if (missingControls.Count > 0)
        {
            Assert.Fail($"Missing WPF terminal controls after authenticated subscription: {string.Join(", ", missingControls)}");
        }
    }

}
