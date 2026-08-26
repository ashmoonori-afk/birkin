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
    public async Task Send_WhenProviderFreeBridgeIsReady_ProjectsCanonicalConversationIntoWpf()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(45));
        await using var bridge = await BridgeProcessHarness.StartAsync(deadline.Token, providerFree: true);
        var announcementJson = await bridge.WaitForListeningAsync(deadline.Token);
        var announcementFile = Path.Combine(bridge.TemporaryRoot, "announcement.jsonl");
        await File.WriteAllTextAsync(announcementFile, announcementJson + Environment.NewLine, deadline.Token);
        var options = AppOptions.Parse(["--bridge-announcement-file", announcementFile]);
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        var journey = await sta.InvokeAsync(async () =>
        {
            await using var composition = CompositionRoot.Create(
                SynchronizationContext.Current
                ?? throw new InvalidOperationException("WPF dispatcher synchronization context is unavailable"));
            var initial = new TaskCompletionSource<WorkspaceSnapshotPresentation>(TaskCreationOptions.RunContinuationsAsynchronously);
            var completed = new TaskCompletionSource<WorkspaceSnapshotPresentation>(TaskCreationOptions.RunContinuationsAsynchronously);
            composition.Coordinator.SnapshotApplied += InitialApplied;
            try
            {
                await composition.Runner.RunAsync(options, deadline.Token);
                var ready = await initial.Task.WaitAsync(deadline.Token);
                var window = new MainWindow(composition.PresentationModel, composition.Coordinator)
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
                    var draft = OfficeWorkflowViewHarness.Find<TextBox>(window, "conversation.draft");
                    var send = OfficeWorkflowViewHarness.Find<Button>(window, "conversation.send");
                    composition.Coordinator.SnapshotApplied += Completed;
                    draft.Text = "provider-free-turn";

                    // When
                    send.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                    _ = await completed.Task.WaitAsync(deadline.Token);
                    await window.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.DataBind);
                    window.UpdateLayout();

                    // Then
                    var current = composition.PresentationModel.Workspace
                        ?? throw new AssertFailedException("workspace presentation is unavailable");
                    Assert.IsTrue(composition.Session.AdvertisedCommands.Contains("chat.send"));
                    Assert.IsTrue(ready.Composer.CanSend);
                    Assert.IsTrue(current.Conversation.Any(row => row.Kind == "user_message"));
                    Assert.IsTrue(current.Conversation.Any(row =>
                        row.Kind == "assistant_message" && !string.IsNullOrWhiteSpace(row.Text)));
                    var rendered = OfficeWorkflowViewHarness.Find<ItemsControl>(window, "conversation.items")
                        .Items.Cast<ConversationRowPresentation>().ToArray();
                    if (current.Conversation.Count != rendered.Length)
                    {
                        Assert.Fail($"model={string.Join(',', current.Conversation.Select(row => row.Kind))};rendered={string.Join(',', rendered.Select(row => row.Kind))}");
                    }
                    Assert.IsTrue(composition.PresentationModel.OfficeWorkflow.Availability.ConversationSend.IsEnabled);
                    Assert.AreEqual(current.Cursor, composition.ProjectionStore.State?.Cursor);
                }
                finally
                {
                    composition.Coordinator.SnapshotApplied -= Completed;
                    window.Close();
                }
            }
            finally
            {
                composition.Coordinator.SnapshotApplied -= InitialApplied;
            }

            void InitialApplied(WorkspaceSnapshotPresentation snapshot) => initial.TrySetResult(snapshot);
            void Completed(WorkspaceSnapshotPresentation snapshot)
            {
                if (snapshot.Conversation.Any(row => row.Kind == "assistant_message"))
                {
                    completed.TrySetResult(snapshot);
                }
            }
        });
        await journey.WaitAsync(deadline.Token);

        Assert.AreEqual(string.Empty, bridge.StandardError, bridge.StandardError);
    }

}
