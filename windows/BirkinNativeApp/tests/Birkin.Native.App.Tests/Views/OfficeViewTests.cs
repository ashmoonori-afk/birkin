using System.Reflection;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Threading;
using Birkin.Native.App;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Birkin.Native.Protocol.Framing;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class OfficeViewTests
{
    [TestMethod]
    public async Task MainWindow_PreviewDrop_RoutesFileDataToImport()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var window = new MainWindow(fixture.Model, fixture.Coordinator);
            try
            {
                var shell = OfficeWorkflowViewHarness.Snapshot(window);
                OfficeWorkflowViewHarness.Layout(shell, 1500, 940);
                var importPanel = OfficeWorkflowViewHarness.Find<Expander>(
                    shell,
                    "office.import-panel");
                var selected = @"C:\fixtures\first-report.xlsx";
                var data = new DataObject(
                    DataFormats.FileDrop,
                    new[] { selected });
                var eventArgs = CreateDropEvent(data, window);
                var sent = fixture.Connection.FirstCommandSent.WaitAsync(
                    deadline.Token);

                window.RaiseEvent(eventArgs);
                var command = await sent;

                Assert.IsTrue(eventArgs.Handled);
                Assert.IsTrue(importPanel.IsExpanded);
                Assert.AreEqual("file.import", command.CommandType);
                Assert.AreEqual(
                    selected,
                    ((NativeJsonString)command.Payload["source_path"]!).Value);
            }
            finally
            {
                window.Close();
            }
        });
    }

    [TestMethod]
    public async Task Drop_WhenImportPanelIsCollapsed_ExpandsVisibleFeedback()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new OfficeView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            var importPanel = OfficeWorkflowViewHarness.Find<Expander>(
                view,
                "office.import-panel");
            Assert.IsFalse(importPanel.IsExpanded);

            var submitted = await view.ImportDroppedFilesAsync(
                [@"C:\fixtures\first-report.xlsx"]);

            Assert.IsTrue(submitted);
            Assert.IsTrue(importPanel.IsExpanded);
        });
    }

    [TestMethod]
    public async Task Save_WhenNoApprovedJobRequest_IsVisiblyDisabledAndSendsNothing()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new OfficeView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            var panel = OfficeWorkflowViewHarness.Find<Expander>(
                view,
                "office.new-panel");
            panel.IsExpanded = true;
            view.UpdateLayout();
            var save = OfficeWorkflowViewHarness.Find<Button>(view, "office.save-unavailable");

            // When / Then
            Assert.IsFalse(save.IsEnabled);
            Assert.AreEqual(0, fixture.Connection.Sent.Count);
            Assert.AreEqual(
                "Office save unavailable without approved job request",
                AutomationProperties.GetName(save));
        });
    }

    [TestMethod]
    public async Task MainWindow_WhenWorkflowIsAttached_PreservesShellRegionsAndContextualControls()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        // When
        var automationIds = await sta.InvokeAsync(() =>
        {
            var fixture = OfficeWorkflowViewHarness.CreateAsync().GetAwaiter().GetResult();
            var window = new MainWindow(fixture.Model, fixture.Coordinator);
            var shell = OfficeWorkflowViewHarness.Snapshot(window);
            OfficeWorkflowViewHarness.Layout(shell, 1500, 940);
            var ids = new[]
            {
                "navigation.sessions", "working-memory.landmark", "conversation.stream",
                "terminal.landmark", "approvals.landmark", "activity.landmark",
                "browser.landmark", "office.landmark", "conversation.send",
                "office.import-panel", "approval.approve.approval-7",
                "office.new-panel", "diff.landmark",
            };
            var result = ids.Select(id => AutomationProperties.GetAutomationId(
                OfficeWorkflowViewHarness.Find<FrameworkElement>(shell, id))).ToArray();
            window.Close();
            fixture.DisposeAsync().AsTask().GetAwaiter().GetResult();
            return result;
        });

        // Then
        CollectionAssert.AreEqual(
            new[]
            {
                "navigation.sessions", "working-memory.landmark", "conversation.stream",
                "terminal.landmark", "approvals.landmark", "activity.landmark",
                "browser.landmark", "office.landmark", "conversation.send",
                "office.import-panel", "approval.approve.approval-7",
                "office.new-panel", "diff.landmark",
            },
            automationIds);
    }

    [TestMethod]
    public async Task ContextRail_WhenWindowIsConstrained_ScrollsCompleteOfficeActionAboveStatus()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        // When
        var geometry = await sta.InvokeAsync(() =>
        {
            var fixture = OfficeWorkflowViewHarness.CreateAsync().GetAwaiter().GetResult();
            var window = new MainWindow(fixture.Model, fixture.Coordinator);
            var shell = OfficeWorkflowViewHarness.Snapshot(window);
            OfficeWorkflowViewHarness.Layout(shell, 1100, 669);
            var scroll = OfficeWorkflowViewHarness.Find<ScrollViewer>(shell, "context.scroll");
            var activity = OfficeWorkflowViewHarness.Find<FrameworkElement>(shell, "activity.landmark");
            var browser = OfficeWorkflowViewHarness.Find<FrameworkElement>(shell, "browser.landmark");
            var office = OfficeWorkflowViewHarness.Find<FrameworkElement>(shell, "office.landmark");
            var newPanel = OfficeWorkflowViewHarness.Find<Expander>(shell, "office.new-panel");
            var status = OfficeWorkflowViewHarness.Find<FrameworkElement>(shell, "workspace.status");
            newPanel.IsExpanded = true;
            shell.UpdateLayout();
            var action = OfficeWorkflowViewHarness.Find<Button>(shell, "office.save-unavailable");
            action.BringIntoView();
            shell.Dispatcher.Invoke(() => { }, DispatcherPriority.Background);
            var actionTop = action.TransformToAncestor(scroll).Transform(new Point()).Y;
            var scrollBottom = scroll.TransformToAncestor(shell).Transform(new Point()).Y + scroll.ActualHeight;
            var statusTop = status.TransformToAncestor(shell).Transform(new Point()).Y;
            var result = new ContextGeometry(
                new PanelGeometry(activity.ActualHeight, browser.ActualHeight, office.ActualHeight),
                new ScrollGeometry(scroll.ScrollableHeight, scroll.VerticalOffset, scroll.ActualHeight),
                new ReachGeometry(actionTop, actionTop + action.ActualHeight, statusTop - scrollBottom));
            window.Close();
            fixture.DisposeAsync().AsTask().GetAwaiter().GetResult();
            return result;
        });

        // Then
        Console.WriteLine(
            $"CONTEXT_GEOMETRY=activity:{geometry.Panels.Activity:F0};browser:{geometry.Panels.Browser:F0};office:{geometry.Panels.Office:F0};scrollable:{geometry.Scroll.Scrollable:F0};offset:{geometry.Scroll.Offset:F0};action_top:{geometry.Reach.ActionTop:F0};action_bottom:{geometry.Reach.ActionBottom:F0};viewport:{geometry.Scroll.Viewport:F0};status_gap:{geometry.Reach.StatusGap:F0}");
        Assert.IsTrue(geometry.Panels.Activity is >= 180 and <= 220);
        Assert.IsTrue(geometry.Panels.Browser is >= 120 and <= 145);
        Assert.IsTrue(geometry.Panels.Office is >= 260 and <= 330);
        Assert.IsTrue(geometry.Scroll.Scrollable > 0);
        Assert.IsTrue(geometry.Scroll.Offset > 0);
        Assert.IsTrue(geometry.Reach.ActionTop >= 0);
        Assert.IsTrue(geometry.Reach.ActionBottom <= geometry.Scroll.Viewport + 1);
        Assert.IsTrue(geometry.Reach.StatusGap >= -1);
    }

    private sealed record ContextGeometry(
        PanelGeometry Panels,
        ScrollGeometry Scroll,
        ReachGeometry Reach);

    private sealed record PanelGeometry(double Activity, double Browser, double Office);
    private sealed record ScrollGeometry(double Scrollable, double Offset, double Viewport);
    private sealed record ReachGeometry(double ActionTop, double ActionBottom, double StatusGap);

    private static DragEventArgs CreateDropEvent(
        IDataObject data,
        DependencyObject target)
    {
        var constructor = typeof(DragEventArgs).GetConstructor(
            BindingFlags.Instance | BindingFlags.NonPublic,
            binder: null,
            [
                typeof(IDataObject),
                typeof(DragDropKeyStates),
                typeof(DragDropEffects),
                typeof(DependencyObject),
                typeof(Point),
            ],
            modifiers: null);
        Assert.IsNotNull(constructor);
        var eventArgs = (DragEventArgs)constructor.Invoke(
            [
                data,
                DragDropKeyStates.None,
                DragDropEffects.Copy,
                target,
                new Point(),
            ]);
        eventArgs.RoutedEvent = DragDrop.PreviewDropEvent;
        return eventArgs;
    }
}
