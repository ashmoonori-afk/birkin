using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Threading;
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
    public async Task Create_WhenAdvertised_SubmitsExplicitDocumentValuesOnce()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new OfficeView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            OfficeWorkflowViewHarness.Find<TextBox>(view, "office.output-name").Text = "comparison-report.docx";
            OfficeWorkflowViewHarness.Find<TextBox>(view, "office.content").Text = "BIRKIN_P3_03_DOCUMENT_SENTINEL";
            var create = OfficeWorkflowViewHarness.Find<Button>(view, "office.create");

            // When
            create.RaiseEvent(new System.Windows.RoutedEventArgs(Button.ClickEvent));

            // Then
            Assert.AreEqual(1, fixture.Connection.Sent.Count);
            Assert.AreEqual("office.create", fixture.Connection.Sent[0].CommandType);
            Assert.AreEqual("comparison-report.docx", ((NativeJsonString)fixture.Connection.Sent[0].Payload["output_name"]!).Value);
            Assert.AreEqual("Create office document", AutomationProperties.GetName(create));
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
            var shell = (WorkspaceSnapshotView)window.Content;
            OfficeWorkflowViewHarness.Layout(shell, 1500, 940);
            var ids = new[]
            {
                "navigation.sessions", "working-memory.landmark", "conversation.stream",
                "terminal.landmark", "approvals.landmark", "activity.landmark",
                "browser.landmark", "office.landmark", "conversation.send",
                "office.import-panel", "approval.approve", "office.new-panel", "diff.landmark",
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
                "office.import-panel", "approval.approve", "office.new-panel", "diff.landmark",
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
            var shell = (WorkspaceSnapshotView)window.Content;
            OfficeWorkflowViewHarness.Layout(shell, 1100, 669);
            var scroll = OfficeWorkflowViewHarness.Find<ScrollViewer>(shell, "context.scroll");
            var activity = OfficeWorkflowViewHarness.Find<FrameworkElement>(shell, "activity.landmark");
            var browser = OfficeWorkflowViewHarness.Find<FrameworkElement>(shell, "browser.landmark");
            var office = OfficeWorkflowViewHarness.Find<FrameworkElement>(shell, "office.landmark");
            var newPanel = OfficeWorkflowViewHarness.Find<Expander>(shell, "office.new-panel");
            var status = OfficeWorkflowViewHarness.Find<FrameworkElement>(shell, "workspace.status");
            newPanel.IsExpanded = true;
            shell.UpdateLayout();
            var action = OfficeWorkflowViewHarness.Find<Button>(shell, "office.create");
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
        Assert.IsTrue(geometry.Panels.Activity >= 180);
        Assert.IsTrue(geometry.Panels.Browser >= 180);
        Assert.IsTrue(geometry.Panels.Office >= 190);
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
}
