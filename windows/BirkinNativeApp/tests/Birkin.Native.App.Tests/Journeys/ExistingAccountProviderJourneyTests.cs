using System.ComponentModel;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Birkin.Native.App.Startup;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Journeys;

[TestClass]
public sealed class ExistingAccountProviderJourneyTests
{
    private const string Prompt = "Reply with exactly PACKAGED_PROVIDER_COMPLETION_OK and no other text.";
    private const string Marker = "PACKAGED_PROVIDER_COMPLETION_OK";
    private const string MarkerSha256 = "97e1434f1402ea1678d9fba3aa66906c842dff8536f20114da93f5b1500bf5f4";

    [TestMethod]
    [TestCategory("ExistingAccountProvider")]
    public async Task Window_WhenExistingAccountProviderCompletes_ProjectsExactAssistantMarker()
    {
        // Given
        if (!string.Equals(Environment.GetEnvironmentVariable("BIRKIN_EXISTING_ACCOUNT_RUNNER"), "1", StringComparison.Ordinal))
        {
            Assert.Inconclusive("Set BIRKIN_EXISTING_ACCOUNT_RUNNER=1 on the protected Windows runner.");
        }

        var repository = new DirectoryInfo(AppContext.BaseDirectory);
        while (repository is not null && !File.Exists(Path.Combine(repository.FullName, "pyproject.toml")))
        {
            repository = repository.Parent;
        }
        var repositoryRoot = repository?.FullName
            ?? throw new InvalidOperationException("repository root was not found");
        var evidence = new ExistingAccountProviderHarness(repositoryRoot);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(180));
        await using var bridge = await BridgeProcessHarness.StartAsync(deadline.Token);
        var announcementJson = await bridge.WaitForListeningAsync(deadline.Token);
        var announcementFile = Path.Combine(bridge.TemporaryRoot, "announcement.jsonl");
        await File.WriteAllTextAsync(announcementFile, announcementJson + Environment.NewLine, deadline.Token);
        var options = AppOptions.Parse(["--bridge-announcement-file", announcementFile]);
        var announcement = BridgeAnnouncement.Parse(options.BridgeAnnouncementJson);
        evidence.Record("bridge-listening", new Dictionary<string, object?>
        {
            ["pid"] = bridge.ProcessId,
            ["transport"] = "loopback",
            ["session_id"] = announcement.SessionId,
            ["instance_id"] = announcement.InstanceId,
            ["server_version"] = announcement.ServerVersion,
        });
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        var journey = await sta.InvokeAsync(async () =>
        {
            await using var composition = CompositionRoot.Create(SynchronizationContext.Current
                ?? throw new InvalidOperationException("WPF dispatcher synchronization context is unavailable"));
            var initialSnapshot = new TaskCompletionSource<WorkspaceSnapshotPresentation>(TaskCreationOptions.RunContinuationsAsynchronously);
            composition.Coordinator.SnapshotApplied += snapshot => initialSnapshot.TrySetResult(snapshot);

            await composition.Runner.RunAsync(options, deadline.Token);
            var ready = await initialSnapshot.Task.WaitAsync(deadline.Token);
            evidence.Record("ready", new Dictionary<string, object?>
            {
                ["cursor"] = ready.Cursor,
                ["connection_state"] = composition.PresentationModel.Connection.State.ToString(),
            });
            Assert.AreEqual(ConnectionState.Ready, composition.PresentationModel.Connection.State);

            Assert.IsTrue(composition.Session.OwnsReceiveLoop, "production session must own the sole receive loop");
            evidence.Record("advertised-command", new Dictionary<string, object?>
            {
                ["chat.send"] = composition.Session.AdvertisedCommands.Contains("chat.send"),
                ["command_count"] = composition.Session.AdvertisedCommands.Count,
            });
            Assert.IsTrue(composition.Session.AdvertisedCommands.Contains("chat.send"), "ready did not advertise chat.send");

            var window = new MainWindow(composition.PresentationModel, composition.Coordinator)
            {
                Width = 1500,
                Height = 940,
                WindowStartupLocation = WindowStartupLocation.Manual,
                Left = 24,
                Top = 24,
            };
            window.Show();
            window.Activate();
            window.UpdateLayout();

            try
            {
                var draft = OfficeWorkflowViewHarness.Find<TextBox>(window, "conversation.draft");
                var send = OfficeWorkflowViewHarness.Find<Button>(window, "conversation.send");
                draft.Text = Prompt;
                evidence.Record("composer-ready", new Dictionary<string, object?>
                {
                    ["send_enabled"] = send.IsEnabled,
                    ["draft_bytes"] = System.Text.Encoding.UTF8.GetByteCount(draft.Text),
                });
                Assert.IsTrue(send.IsEnabled, "real advertised authority did not enable Send");

                var submitted = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                var receipt = new TaskCompletionSource<OfficeWorkflowPresentation>(TaskCreationOptions.RunContinuationsAsynchronously);
                var completed = new TaskCompletionSource<WorkspaceSnapshotPresentation>(TaskCreationOptions.RunContinuationsAsynchronously);
                var projectionCursors = new List<long>();
                string? commandId = null;
                long? acceptedCursor = null;
                var projectedFrames = 0;

                PropertyChangedEventHandler workflowChanged = (_, eventArgs) =>
                {
                    if (eventArgs.PropertyName != nameof(ShellPresentationModel.OfficeWorkflow))
                    {
                        return;
                    }
                    var workflow = composition.PresentationModel.OfficeWorkflow;
                    evidence.Record("workflow", new Dictionary<string, object?>
                    {
                        ["state"] = workflow.CommandState.ToString(),
                        ["command_id"] = workflow.CommandId,
                        ["command_type"] = workflow.CommandType,
                        ["accepted_cursor"] = workflow.AcceptedCursor,
                        ["current_cursor"] = workflow.CurrentCursor,
                        ["refusal_code"] = workflow.RefusalCode,
                    });
                    if (workflow.CommandType == "chat.send" && workflow.CommandId is not null)
                    {
                        commandId ??= workflow.CommandId;
                        submitted.TrySetResult(true);
                    }
                    if (workflow.CommandState is WorkflowCommandState.AcceptedPendingProjection or WorkflowCommandState.Refused)
                    {
                        acceptedCursor = workflow.AcceptedCursor;
                        receipt.TrySetResult(workflow);
                    }
                };
                void ProjectionApplied(WorkspaceSnapshotPresentation snapshot)
                {
                    projectedFrames++;
                    projectionCursors.Add(snapshot.Cursor);
                    evidence.RecordProjection(snapshot);
                    var rows = snapshot.Conversation;
                    var userIndex = rows.Select((row, index) => (row, index)).LastOrDefault(item =>
                        item.row.Kind == "user_message" && item.row.Text == Prompt).index;
                    if (rows.Count > 0
                        && rows[userIndex].Kind == "user_message"
                        && rows.Skip(userIndex + 1).Any(row =>
                            row.Kind == "assistant_message" && row.Text.Trim() == Marker))
                    {
                        completed.TrySetResult(snapshot);
                    }
                }

                composition.PresentationModel.PropertyChanged += workflowChanged;
                composition.Coordinator.SnapshotApplied += ProjectionApplied;
                try
                {
                    // When
                    evidence.Record("before-click", new Dictionary<string, object?>());
                    send.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                    evidence.Record("after-click", new Dictionary<string, object?>());
                    await submitted.Task.WaitAsync(deadline.Token);
                    evidence.Record("command-submitted", new Dictionary<string, object?> { ["command_id"] = commandId });
                    var receiptState = await receipt.Task.WaitAsync(deadline.Token);
                    evidence.Record("receipt-observed", new Dictionary<string, object?>
                    {
                        ["state"] = receiptState.CommandState.ToString(),
                        ["accepted_cursor"] = receiptState.AcceptedCursor,
                        ["refusal_code"] = receiptState.RefusalCode,
                    });
                    Assert.AreEqual(
                        WorkflowCommandState.AcceptedPendingProjection,
                        receiptState.CommandState,
                        $"chat receipt was refused: {receiptState.RefusalCode}");
                    var final = await completed.Task.WaitAsync(deadline.Token);

                    // Then
                    var user = final.Conversation.Last(row => row.Kind == "user_message" && row.Text == Prompt);
                    var userIndex = final.Conversation.Select((row, index) => (row, index))
                        .Single(item => item.row.Id == user.Id).index;
                    var validatedAssistant = AssistantSentinelValidator.ValidateExact(
                        final.Conversation.Skip(userIndex + 1)
                            .Where(row => row.Kind == "assistant_message")
                            .Select(row => new AssistantSentinelRow(row.Id, row.Text))
                            .ToArray(),
                        Marker,
                        MarkerSha256);
                    var assistant = final.Conversation.Single(row => row.Id == validatedAssistant.Id);
                    Assert.IsNotNull(commandId);
                    Assert.IsNotNull(acceptedCursor);
                    Assert.IsTrue(final.Cursor >= assistant.Cursor);
                    Assert.AreEqual(1, composition.Session.MaximumConcurrentReceives, "provider journey used more than the production session pump");

                    window.UpdateLayout();
                    var renderedWindow = (FrameworkElement)window.Content;
                    var bitmap = new RenderTargetBitmap(
                        (int)Math.Ceiling(renderedWindow.ActualWidth),
                        (int)Math.Ceiling(renderedWindow.ActualHeight),
                        96,
                        96,
                        PixelFormats.Pbgra32);
                    bitmap.Render(renderedWindow);
                    var encoder = new PngBitmapEncoder();
                    encoder.Frames.Add(BitmapFrame.Create(bitmap));
                    var evidencePath = Path.Combine(
                        repositoryRoot,
                        ".omo", "evidence", "native-windows-20260824", "live-chat", "real-conversation.png");
                    Directory.CreateDirectory(Path.GetDirectoryName(evidencePath)!);
                    await using (var output = File.Create(evidencePath))
                    {
                        encoder.Save(output);
                    }

                    Console.WriteLine($"READY_COMMAND=chat.send;transport={ready.Transport};session_id={ready.SessionId}");
                    Console.WriteLine($"CHAT_COMMAND=id={commandId};accepted_cursor={acceptedCursor};final_cursor={final.Cursor};projected_frames={projectedFrames};cursor_sequence={string.Join(',', projectionCursors)}");
                    var assistantText = assistant.Text.Trim();
                    Console.WriteLine($"CHAT_ROWS=user_id={user.Id};user_cursor={user.Cursor};assistant_id={assistant.Id};assistant_cursor={assistant.Cursor};assistant_text_bytes={System.Text.Encoding.UTF8.GetByteCount(assistantText)};assistant_text_sha256={ProviderOfficeEvidence.Hash(assistantText)}");
                    Console.WriteLine($"RECEIPT=state=accepted;command_id={commandId};accepted_cursor={acceptedCursor}");
                    Console.WriteLine($"SCREENSHOT={evidencePath}");
                }
                finally
                {
                    composition.PresentationModel.PropertyChanged -= workflowChanged;
                    composition.Coordinator.SnapshotApplied -= ProjectionApplied;
                }
            }
            finally
            {
                window.Close();
            }
        });
        try
        {
            await journey.WaitAsync(deadline.Token);
        }
        catch
        {
            try
            {
                await journey.WaitAsync(TimeSpan.FromSeconds(10));
            }
            catch (Exception unwindError)
            {
                evidence.Record("journey-unwind-failed", new Dictionary<string, object?>
                {
                    ["error_type"] = unwindError.GetType().Name,
                });
            }
            evidence.CaptureWorkspace(bridge.TemporaryRoot);
            evidence.Record("bridge-diagnostics", new Dictionary<string, object?>
            {
                ["stderr_empty"] = string.IsNullOrEmpty(bridge.StandardError),
                ["stderr_bytes"] = System.Text.Encoding.UTF8.GetByteCount(bridge.StandardError),
                ["stderr_sha256"] = ProviderOfficeEvidence.Hash(bridge.StandardError),
                ["launcher_diagnostics_bytes"] = System.Text.Encoding.UTF8.GetByteCount(bridge.LauncherDiagnostics),
                ["launcher_diagnostics_sha256"] = ProviderOfficeEvidence.Hash(bridge.LauncherDiagnostics),
            });
            throw;
        }
        evidence.CaptureWorkspace(bridge.TemporaryRoot);

        RedactedDiagnostics.AssertEmpty("bridge_stderr", bridge.StandardError);
        Console.WriteLine($"BRIDGE=pid={bridge.ProcessId};transport=loopback;stderr_empty=true;temporary_root={bridge.TemporaryRoot}");
    }
}
