using System.ComponentModel;
using System.IO;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Media;
using Birkin.Native.App.Startup;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Lifecycle;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Journeys;

[TestClass]
public sealed class DeterministicWindowJourneyTests : MainWindowTestBase
{
    [TestMethod]
    [TestCategory("LiveBridge")]
    [TestCategory("DeterministicWindow")]
    public async Task MainWindow_WhenPythonEmitsCanonicalEvent_UpdatesVisibleHierarchyThroughProductionSessionPump()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(45));
        var bridge = await BridgeProcessHarness.StartAsync(deadline.Token);
        await using (bridge)
        {
            var announcementJson = await bridge.WaitForListeningAsync(deadline.Token);
            var announcementFile = Path.Combine(bridge.TemporaryRoot, "announcement.jsonl");
            await File.WriteAllTextAsync(announcementFile, announcementJson + Environment.NewLine, deadline.Token);
            var options = AppOptions.Parse(["--bridge-announcement-file", announcementFile]);
            var announcement = Birkin.Native.Protocol.Transport.BridgeAnnouncement.Parse(options.BridgeAnnouncementJson);
            await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

            var stage = "dispatcher-start";
            var journey = sta.InvokeAsync(async () =>
            {
                await using var composition = CompositionRoot.Create(
                    SynchronizationContext.Current
                    ?? throw new InvalidOperationException("WPF dispatcher synchronization context is unavailable"));
                var initialApplied = new TaskCompletionSource<WorkspaceSnapshotPresentation>(TaskCreationOptions.RunContinuationsAsynchronously);
                var initialPresented = new TaskCompletionSource<WorkspaceSnapshotPresentation>(TaskCreationOptions.RunContinuationsAsynchronously);
                var canonicalApplied = new TaskCompletionSource<NativeEnvelope>(TaskCreationOptions.RunContinuationsAsynchronously);
                var presentationApplied = new TaskCompletionSource<WorkspaceSnapshotPresentation>(TaskCreationOptions.RunContinuationsAsynchronously);
                composition.Coordinator.SnapshotApplied += InitialSnapshotApplied;
                composition.PresentationModel.PropertyChanged += InitialWorkspacePresented;

                var window = new MainWindow(composition.PresentationModel)
                {
                    Width = 1500,
                    Height = 940,
                    WindowStartupLocation = WindowStartupLocation.Manual,
                    Left = 24,
                    Top = 24,
                };
                window.Show();
                window.Activate();

                try
                {
                    stage = "production-startup";
                    await composition.Runner.RunAsync(options, deadline.Token);
                    var initial = await initialApplied.Task.WaitAsync(deadline.Token);
                    var presentedInitial = await initialPresented.Task.WaitAsync(deadline.Token);
                    stage = "initial-render";
                    window.UpdateLayout();
                    var renderedInitial = composition.PresentationModel.Workspace;
                    Assert.IsNotNull(renderedInitial);

                    Assert.IsTrue(options.IsAttached, "journey must attach to the exact bridge owned by its harness");
                    Assert.AreEqual(BridgeSupervisorState.AttachedExternal, composition.Supervisor.State);
                    Assert.IsNull(composition.Supervisor.OwnedProcess);
                    var attachment = composition.Supervisor.Attachment as BridgeAttachment.AttachedExternal;
                    Assert.IsNotNull(attachment);
                    Assert.AreEqual(announcement.ProcessId, attachment.ProcessId);
                    Assert.IsTrue(composition.Session.OwnsReceiveLoop);
                    Assert.AreEqual(1, composition.Session.MaximumConcurrentReceives);
                    Assert.AreEqual(ConnectionState.Ready, composition.PresentationModel.Connection.State);
                    Assert.AreSame(initial, presentedInitial);
                    Assert.AreEqual(announcement.SessionId, initial.SessionId);
                    Assert.AreEqual(announcement.InstanceId, initial.InstanceId);
                    Assert.AreEqual("initial", initial.ResetReason);
                    Assert.IsTrue(initial.Cursor >= 0);
                    Assert.IsTrue(initial.PanelCount > 0);
                    Assert.AreEqual(initial.SessionId, renderedInitial.SessionId);
                    Assert.AreEqual(initial.InstanceId, renderedInitial.InstanceId);
                    Assert.IsTrue(renderedInitial.Cursor >= initial.Cursor);
                    AssertBoundText(window, "SessionIdText", renderedInitial.SessionId);
                    AssertBoundText(window, "CursorText", renderedInitial.Cursor.ToString(System.Globalization.CultureInfo.InvariantCulture));
                    AssertBoundText(window, "PanelCountText", renderedInitial.PanelCount.ToString(System.Globalization.CultureInfo.InvariantCulture));
                    AssertVisibleHierarchy(window);

                    composition.ProjectionStore.CanonicalApplied += CanonicalApplied;
                    composition.Coordinator.SnapshotApplied += PresentationApplied;
                    try
                    {
                        stage = "office-import";
                        var fixturePath = Path.Combine(
                            AppContext.BaseDirectory,
                            "Fixtures",
                            "Office",
                            "baseline.xlsx");
                        var submitted = await composition.Coordinator.ImportAsync(
                            new FileImportIntent(fixturePath),
                            deadline.Token);
                        Assert.IsTrue(submitted, "real Python authority refused the read-only Office import");

                        stage = "canonical-event";
                        var canonical = await canonicalApplied.Task.WaitAsync(deadline.Token);
                        stage = "dispatcher-presentation";
                        var presented = await presentationApplied.Task.WaitAsync(deadline.Token);
                        Assert.IsTrue(presented.Cursor >= Integer(canonical.Body, "cursor"));
                        Assert.IsTrue(presented.Cursor > initial.Cursor);
                        Assert.AreEqual(1, composition.Session.MaximumConcurrentReceives,
                            "a receive path outside the production session pump was used");

                        window.UpdateLayout();
                        var activity = FindByAutomationId<FrameworkElement>(window, "activity.landmark");
                        Assert.IsTrue(Descendants<TextBlock>(activity).Any(text =>
                            string.Equals(text.Text, "command.completed", StringComparison.Ordinal)),
                            "Python's canonical completion was not visible in the bound Activity hierarchy");
                        AssertVisibleHierarchy(window);
                    }
                    finally
                    {
                        composition.ProjectionStore.CanonicalApplied -= CanonicalApplied;
                        composition.Coordinator.SnapshotApplied -= PresentationApplied;
                    }
                }
                finally
                {
                    composition.Coordinator.SnapshotApplied -= InitialSnapshotApplied;
                    composition.PresentationModel.PropertyChanged -= InitialWorkspacePresented;
                    window.Close();
                }

                void InitialSnapshotApplied(WorkspaceSnapshotPresentation snapshot) =>
                    initialApplied.TrySetResult(snapshot);

                void InitialWorkspacePresented(
                    object? sender,
                    PropertyChangedEventArgs eventArgs)
                {
                    if (eventArgs.PropertyName
                            == nameof(ShellPresentationModel.Workspace)
                        && composition.PresentationModel.Workspace is
                            { } workspace)
                    {
                        initialPresented.TrySetResult(workspace);
                    }
                }

                void CanonicalApplied(NativeEnvelope envelope)
                {
                    if (envelope.Kind == NativeMessageKind.Event
                        && String(envelope.Body, "type") == "command.completed")
                    {
                        canonicalApplied.TrySetResult(envelope);
                    }
                }

                void PresentationApplied(WorkspaceSnapshotPresentation snapshot)
                {
                    if (snapshot.Activity.Any(row =>
                        string.Equals(row.Summary, "command.completed", StringComparison.Ordinal)))
                    {
                        presentationApplied.TrySetResult(snapshot);
                    }
                }
            });
            try
            {
                await journey.WaitAsync(deadline.Token);
            }
            catch (OperationCanceledException error) when (deadline.IsCancellationRequested)
            {
                throw new InvalidOperationException(
                    $"deterministic window journey timed out during {stage}; bridge stderr: {bridge.StandardError}",
                    error);
            }
            Assert.AreEqual(string.Empty, bridge.StandardError, bridge.StandardError);
        }

        Assert.IsTrue(bridge.OwnedProcessExited, "the harness did not stop its exact owned Process object");
        Assert.IsTrue(bridge.TemporaryRootDeleted, "the harness did not delete its exact temporary root");
        Assert.IsFalse(Directory.Exists(bridge.TemporaryRoot));
    }

    private static void AssertVisibleHierarchy(DependencyObject window)
    {
        foreach (var automationId in new[]
        {
            "navigation.sessions",
            "working-memory.landmark",
            "conversation.landmark",
            "terminal.landmark",
            "approvals.landmark",
            "activity.landmark",
            "browser.landmark",
            "office.landmark",
        })
        {
            Assert.AreEqual(
                Visibility.Visible,
                FindByAutomationId<FrameworkElement>(window, automationId).Visibility,
                $"{automationId} left the visible WPF hierarchy");
        }
    }

    private static void AssertBoundText(DependencyObject window, string automationId, string expected) =>
        Assert.AreEqual(expected, FindByAutomationId<TextBlock>(window, automationId).Text);

    private static T FindByAutomationId<T>(DependencyObject root, string automationId)
        where T : DependencyObject => Descendants<T>(root).Single(element =>
            string.Equals(AutomationProperties.GetAutomationId(element), automationId, StringComparison.Ordinal));

    private static IEnumerable<T> Descendants<T>(DependencyObject root)
        where T : DependencyObject
    {
        for (var index = 0; index < VisualTreeHelper.GetChildrenCount(root); index++)
        {
            var child = VisualTreeHelper.GetChild(root, index);
            if (child is T match)
            {
                yield return match;
            }
            foreach (var descendant in Descendants<T>(child))
            {
                yield return descendant;
            }
        }
    }

    private static string String(NativeJsonObject body, string key) =>
        body[key] is NativeJsonString text
            ? text.Value
            : throw new InvalidOperationException($"canonical {key} was not a string");

    private static long Integer(NativeJsonObject body, string key) =>
        body[key] is NativeJsonInteger integer
            ? integer.Value
            : throw new InvalidOperationException($"canonical {key} was not an integer");
}
