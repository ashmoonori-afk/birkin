using System.IO;
using System.Windows;
using System.Windows.Controls;
using Birkin.Native.App.Startup;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Journeys;

[TestClass]
public sealed class CombinedSendTerminalIntegrationTests
{
    [TestMethod]
    [TestCategory("LiveBridge")]
    public async Task SendThenTerminal_WhenOneReleaseSessionIsReady_KeepCanonicalStatesIndependent()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(90));
        var bridge = await BridgeProcessHarness.StartAsync(deadline.Token, providerFree: true);
        var bridgeError = string.Empty;
        var liveStage = "bridge-started";
        var controlState = "not-created";

        await using (bridge)
        {
            var announcementJson = await bridge.WaitForListeningAsync(deadline.Token);
            var announcementFile = Path.Combine(bridge.TemporaryRoot, "announcement.jsonl");
            await File.WriteAllTextAsync(
                announcementFile,
                announcementJson + Environment.NewLine,
                deadline.Token);
            var options = AppOptions.Parse(["--bridge-announcement-file", announcementFile]);
            await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
            var journey = await sta.InvokeAsync(async () =>
            {
                await using var composition = CompositionRoot.Create(
                    SynchronizationContext.Current
                    ?? throw new InvalidOperationException(
                        "WPF dispatcher synchronization context is unavailable"));
                var initial = new TaskCompletionSource<WorkspaceSnapshotPresentation>(
                    TaskCreationOptions.RunContinuationsAsynchronously);
                var sendCompleted = new TaskCompletionSource<WorkspaceSnapshotPresentation>(
                    TaskCreationOptions.RunContinuationsAsynchronously);
                var terminalOpened = new TaskCompletionSource<NativeEnvelope>(
                    TaskCreationOptions.RunContinuationsAsynchronously);
                var terminalAuthorityReady = new TaskCompletionSource<TerminalWorkflowPresentation>(
                    TaskCreationOptions.RunContinuationsAsynchronously);
                var terminalReadyToClose = new TaskCompletionSource<WorkspaceSnapshotPresentation>(
                    TaskCreationOptions.RunContinuationsAsynchronously);
                long? sentinelCursor = null;
                WorkspaceSnapshotPresentation? latestSnapshot = null;
                var terminalExited = new TaskCompletionSource<NativeEnvelope>(
                    TaskCreationOptions.RunContinuationsAsynchronously);

                composition.Coordinator.SnapshotApplied += SnapshotApplied;
                composition.ProjectionStore.CanonicalApplied += CanonicalApplied;
                composition.PresentationModel.PropertyChanged += PresentationChanged;
                try
                {
                    await composition.Runner.RunAsync(options, deadline.Token);
                    liveStage = "await-initial";
                    _ = await initial.Task.WaitAsync(deadline.Token);
                    liveStage = "initial-ready";
                    var window = new MainWindow(
                        composition.PresentationModel,
                        composition.Coordinator)
                    {
                        Width = 1100,
                        Height = 700,
                        WindowStartupLocation = WindowStartupLocation.Manual,
                        Left = 0,
                        Top = 0,
                    };
                    window.Show();
                    try
                    {
                        var draft = OfficeWorkflowViewHarness.Find<TextBox>(
                            window,
                            "conversation.draft");
                        draft.Text = "Reply with exactly SEND_OK";

                        // When: Send is triggered only after every canonical signal is armed.
                        OfficeWorkflowViewHarness.Find<Button>(window, "conversation.send")
                            .RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                        liveStage = "await-send-completed";
                        var sent = await sendCompleted.Task.WaitAsync(deadline.Token);
                        liveStage = "send-completed";
                        Assert.IsTrue(sent.Conversation.Any(row =>
                            row.Kind == "assistant_message"
                            && string.Equals(row.Text.Trim(), "SEND_OK", StringComparison.Ordinal)));
                        var conversation = sent.Conversation
                            .Select(row => (row.Kind, row.Text))
                            .ToArray();
                        var cursorAfterSend = sent.Cursor;

                        // When: the same session then drives the Python-owned terminal.
                        OfficeWorkflowViewHarness.Find<Button>(window, "terminal.create")
                            .RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                        liveStage = "await-terminal-opened";
                        _ = await terminalOpened.Task.WaitAsync(deadline.Token);
                        liveStage = "await-terminal-authority";
                        _ = await terminalAuthorityReady.Task.WaitAsync(deadline.Token);
                        liveStage = "terminal-authority-ready";
                        var input = OfficeWorkflowViewHarness.Find<TextBox>(
                            window,
                            "terminal.input");
                        input.Text = "python -c \"import sys;sys.stdout.buffer.write(bytes.fromhex('434f4e5054595f4f4b'))\"";
                        var terminalSend = OfficeWorkflowViewHarness.Find<Button>(window, "terminal.send");
                        var terminalClose = OfficeWorkflowViewHarness.Find<Button>(window, "terminal.close");
                        controlState = $"send={terminalSend.IsEnabled};close={terminalClose.IsEnabled};window={window.IsVisible}";
                        terminalSend.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                        liveStage = "await-terminal-output";
                        var terminal = await terminalReadyToClose.Task.WaitAsync(deadline.Token);
                        liveStage = "terminal-output";

                        // Then: both outcomes remain canonical without cross-state contamination.
                        Assert.IsTrue(terminal.Cursor > cursorAfterSend);
                        CollectionAssert.AreEqual(
                            conversation,
                            terminal.Conversation.Select(row => (row.Kind, row.Text)).ToArray());
                        Assert.IsTrue(terminal.Terminal.Display.Contains(
                            "CONPTY_OK",
                            StringComparison.Ordinal));
                        terminalClose.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                        liveStage = "await-terminal-exited";
                        _ = await terminalExited.Task.WaitAsync(deadline.Token);
                        liveStage = "terminal-exited";
                    }
                    finally
                    {
                        window.Close();
                    }
                }
                finally
                {
                    composition.Coordinator.SnapshotApplied -= SnapshotApplied;
                    composition.ProjectionStore.CanonicalApplied -= CanonicalApplied;
                    composition.PresentationModel.PropertyChanged -= PresentationChanged;
                }

                void SnapshotApplied(WorkspaceSnapshotPresentation snapshot)
                {
                    latestSnapshot = snapshot;
                    initial.TrySetResult(snapshot);
                    if (snapshot.Conversation.Any(row =>
                        row.Kind == "assistant_message"
                        && string.Equals(row.Text.Trim(), "SEND_OK", StringComparison.Ordinal)))
                    {
                        sendCompleted.TrySetResult(snapshot);
                    }
                    if (snapshot.Terminal.Display.Contains("CONPTY_OK", StringComparison.Ordinal))
                    {
                        sentinelCursor = snapshot.Cursor;
                        TryCompleteTerminalRendezvous(snapshot);
                    }
                }

                void PresentationChanged(
                    object? sender,
                    System.ComponentModel.PropertyChangedEventArgs eventArgs)
                {
                    var terminal = composition.PresentationModel.TerminalWorkflow;
                    if (eventArgs.PropertyName == nameof(ShellPresentationModel.TerminalWorkflow)
                        && terminal.TerminalId is not null
                        && !terminal.HasPendingCommand
                        && terminal.MutationAvailability.Input.IsEnabled)
                    {
                        terminalAuthorityReady.TrySetResult(terminal);
                        if (latestSnapshot is not null)
                        {
                            TryCompleteTerminalRendezvous(latestSnapshot);
                        }
                    }
                }

                void TryCompleteTerminalRendezvous(WorkspaceSnapshotPresentation snapshot)
                {
                    var terminal = composition.PresentationModel.TerminalWorkflow;
                    if (sentinelCursor is { } cursor
                        && terminal.NextInputSequence == 2
                        && !terminal.HasPendingCommand
                        && terminal.CommandState == TerminalCommandState.Idle
                        && terminal.CurrentCursor >= cursor
                        && terminal.MutationAvailability.Close.IsEnabled)
                    {
                        terminalReadyToClose.TrySetResult(snapshot);
                    }
                }

                void CanonicalApplied(NativeEnvelope envelope)
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
                Assert.Fail($"combined journey timed out at {liveStage}; {controlState}; bridge_exited={bridge.OwnedProcessExited}");
            }
            bridgeError = bridge.StandardError;
        }

        Assert.AreEqual(string.Empty, bridgeError, bridgeError);
        Assert.IsTrue(bridge.OwnedProcessExited, "owned bridge survived combined journey cleanup");
        Assert.IsTrue(bridge.TemporaryRootDeleted, "secret-bearing combined journey root survived cleanup");
    }
}
