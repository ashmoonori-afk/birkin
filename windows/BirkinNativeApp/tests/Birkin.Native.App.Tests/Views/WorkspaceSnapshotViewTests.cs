using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Threading;
using System.Windows.Media;
using System.Windows.Shapes;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
public sealed class WorkspaceSnapshotViewTests
{
    [TestMethod]
    public async Task ConnectionIndicator_WhenStateChanges_UsesTruthfulBrush()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        // When / Then
        _ = await sta.InvokeAsync(() =>
        {
            var model = new ShellPresentationModel(
                SynchronizationContext.Current!);
            var view = new WorkspaceSnapshotView(model);
            OfficeWorkflowViewHarness.Layout(view);
            var indicator = FindByAutomationId<Ellipse>(
                view,
                "ConnectionStatusIndicator");
            var cases = new[]
            {
                (ConnectionState.Disconnected, "FaintBrush"),
                (ConnectionState.Connecting, "AccentBrush"),
                (ConnectionState.Handshaking, "AccentBrush"),
                (ConnectionState.Subscribing, "AccentBrush"),
                (ConnectionState.Ready, "SuccessBrush"),
                (ConnectionState.Failed, "DangerBrush"),
            };

            foreach (var (state, resource) in cases)
            {
                model.PresentConnection(
                    state == ConnectionState.Failed
                        ? ConnectionPresentation.Failed("E_CONNECTION")
                        : ConnectionPresentation.Create(state));
                view.Dispatcher.Invoke(
                    () => { },
                    DispatcherPriority.DataBind);
                Assert.AreSame(view.FindResource(resource), indicator.Fill);
            }
            return true;
        });
    }

    [TestMethod]
    public async Task Bindings_WhenPythonPresentationIsReady_RenderNamedValues()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        // When
        var rendered = await sta.InvokeAsync(() =>
        {
            var model = new ShellPresentationModel(SynchronizationContext.Current!);
            var view = new WorkspaceSnapshotView(model);
            model.PresentConnection(ConnectionPresentation.Create(ConnectionState.Ready));
            model.PresentSnapshot(
                new WorkspaceSnapshotPresentation(
                    1,
                    "native-app",
                    42,
                    "0123456789abcdef0123456789abcdef",
                    "initial",
                    "loopback",
                    6),
                () => { });
            view.Dispatcher.Invoke(() => { }, DispatcherPriority.DataBind);
            return new RenderedValues(
                Text(view, "ConnectionStatusText"),
                Text(view, "TransportText"),
                Text(view, "SessionIdText"),
                Text(view, "CursorText"),
                Text(view, "ResetReasonText"),
                Text(view, "PanelCountText"),
                AutomationIds(view));
        });

        // Then
        Assert.AreEqual("LOCAL · PRIVATE", rendered.ConnectionStatus);
        Assert.AreEqual("loopback", rendered.Transport);
        Assert.AreEqual("native-app", rendered.SessionId);
        Assert.AreEqual("42", rendered.Cursor);
        Assert.AreEqual("initial", rendered.ResetReason);
        Assert.AreEqual("6", rendered.PanelCount);
        CollectionAssert.AreEquivalent(
            new[] { "ConnectionStatusText", "TransportText", "SessionIdText", "CursorText", "ResetReasonText", "PanelCountText" },
            rendered.AutomationIds);
    }

    [TestMethod]
    public async Task Bindings_WhenCanonicalRegionsArePresented_RenderValuesAndKeepEveryControlDisabled()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        // When
        var rendered = await sta.InvokeAsync(() =>
        {
            var model = new ShellPresentationModel(SynchronizationContext.Current!);
            var view = new WorkspaceSnapshotView(model);
            model.PresentSnapshot(
                new WorkspaceSnapshotPresentation(
                    1,
                    "session-from-python",
                    9,
                    "instance-from-python",
                    "initial",
                    "loopback",
                    10,
                    "connected",
                    [new ConversationRowPresentation("event-1", "user_message", "canonical text", "python:actor", 9)],
                    new ComposerPresentation(true, false, false, false),
                    new WorkingMemoryPresentation(
                        3,
                        [new WorkingMemoryRowPresentation("Goals", ["canonical goal"], "None set")]),
                    [new ApprovalPolicyRowPresentation("Command Execution", "shell", "Ask", "Default", false)],
                    [],
                    [],
                    [],
                    [],
                    new TerminalPresentation(false, 0),
                    MutationAvailabilityPresentation.PhaseOne),
                () => { });
            view.Measure(new Size(1500, 900));
            view.Arrange(new Rect(0, 0, 1500, 900));
            view.UpdateLayout();
            view.Dispatcher.Invoke(() => { }, DispatcherPriority.DataBind);
            return new RegionBindingValues(
                FindByAutomationId<ItemsControl>(view, "conversation.items").ItemsSource,
                FindByAutomationId<ItemsControl>(view, "working-memory.items").ItemsSource,
                FindByAutomationId<ItemsControl>(view, "approvals.items").ItemsSource,
                RegionAutomationIds(view),
                Descendants<Button>(view)
                    .Where(button => button.IsVisible)
                    .Select(button => button.IsEnabled)
                    .ToArray(),
                FindByAutomationId<TextBox>(view, "conversation.draft").IsEnabled,
                AutomationProperties.GetAutomationId(
                    FindByAutomationId<TextBlock>(view, "composer.read-only-caption")));
        });

        // Then
        Assert.AreEqual(1, rendered.Conversation.Cast<object>().Count());
        Assert.AreEqual(1, rendered.WorkingMemory.Cast<object>().Count());
        Assert.AreEqual(1, rendered.Approvals.Cast<object>().Count());
        CollectionAssert.AreEqual(
            new[]
            {
                "navigation.column", "navigation.sessions", "working-memory.landmark",
                "primary.column", "conversation.stream", "composer.landmark", "terminal.landmark",
                "context.column", "approvals.landmark", "activity.landmark", "browser.landmark", "office.landmark",
            },
            rendered.RegionAutomationIds);
        Assert.IsTrue(rendered.ControlEnabledStates.Length > 0);
        Assert.IsTrue(rendered.ControlEnabledStates.All(enabled => !enabled));
        Assert.IsFalse(rendered.ComposerInputEnabled);
        Assert.AreEqual("composer.read-only-caption", rendered.ComposerCaptionAutomationId);
    }

    [TestMethod]
    public async Task MainWindow_WhenConstructed_UsesDevelopmentPreviewTitleAndAllowsKeyboardFocus()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        // When
        var properties = await sta.InvokeAsync(() =>
        {
            var model = new ShellPresentationModel(SynchronizationContext.Current!);
            var window = new MainWindow(model);
            var result = (window.Title, window.ResizeMode, window.Focusable);
            window.Close();
            return result;
        });

        // Then
        Assert.AreEqual("Birkin for Windows - Development Preview", properties.Title);
        Assert.AreEqual(ResizeMode.CanResize, properties.ResizeMode);
        Assert.IsTrue(properties.Focusable);
    }

    private static string Text(FrameworkElement view, string name) =>
        ((TextBlock)view.FindName(name)).Text;

    private static string[] AutomationIds(FrameworkElement view) =>
        new[] { "ConnectionStatusText", "TransportText", "SessionIdText", "CursorText", "ResetReasonText", "PanelCountText" }
            .Select(name => AutomationProperties.GetAutomationId((DependencyObject)view.FindName(name)))
            .ToArray();

    private static string[] RegionAutomationIds(FrameworkElement view) =>
        new[]
        {
            "navigation.column", "navigation.sessions", "working-memory.landmark",
            "primary.column", "conversation.stream", "composer.landmark", "terminal.landmark",
            "context.column", "approvals.landmark", "activity.landmark", "browser.landmark", "office.landmark",
        }
        .Select(id => AutomationProperties.GetAutomationId(FindByAutomationId<FrameworkElement>(view, id)))
        .ToArray();

    private static T FindByAutomationId<T>(DependencyObject root, string id) where T : DependencyObject =>
        Descendants<T>(root).SingleOrDefault(element =>
            string.Equals(AutomationProperties.GetAutomationId(element), id, StringComparison.Ordinal))
        ?? throw new AssertFailedException($"Missing automation element: {id}");

    private static IEnumerable<T> Descendants<T>(DependencyObject root) where T : DependencyObject
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

    private sealed record RenderedValues(
        string ConnectionStatus,
        string Transport,
        string SessionId,
        string Cursor,
        string ResetReason,
        string PanelCount,
        string[] AutomationIds);

    private sealed record RegionBindingValues(
        System.Collections.IEnumerable Conversation,
        System.Collections.IEnumerable WorkingMemory,
        System.Collections.IEnumerable Approvals,
        string[] RegionAutomationIds,
        bool[] ControlEnabledStates,
        bool ComposerInputEnabled,
        string ComposerCaptionAutomationId);

}
