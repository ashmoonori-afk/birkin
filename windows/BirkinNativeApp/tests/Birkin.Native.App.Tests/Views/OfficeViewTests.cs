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
public sealed class OfficeViewTests : MainWindowTestBase
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
    public async Task Draft_WhenRequiredFieldsAreMissing_ShowsGuidanceAndSendsNothing()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new OfficeView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            var newPanel = OfficeWorkflowViewHarness.Find<Expander>(
                view,
                "office.new-panel");
            newPanel.IsExpanded = true;
            OfficeWorkflowViewHarness.Layout(view);
            var draft = OfficeWorkflowViewHarness.Find<Button>(view, "office.draft");
            var status = OfficeWorkflowViewHarness.Find<TextBlock>(view, "office.request-status");

            draft.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));

            Assert.AreEqual(0, fixture.Connection.Sent.Count);
            StringAssert.Contains(status.Text, "모두 입력");
            Assert.AreEqual("새 DOCX 초안 요청", AutomationProperties.GetName(draft));
        });
    }

    [TestMethod]
    public async Task Draft_WhenFormIsComplete_SubmitsReviewableDocxJobRequest()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new OfficeView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            OfficeWorkflowViewHarness.Find<Expander>(view, "office.new-panel").IsExpanded = true;
            OfficeWorkflowViewHarness.Layout(view);
            OfficeWorkflowViewHarness.Find<TextBox>(view, "office.request").Text = "분기 보고서 작성";
            OfficeWorkflowViewHarness.Find<TextBox>(view, "office.content").Text = "제목\n본문";
            OfficeWorkflowViewHarness.Find<TextBox>(view, "office.destination").Text = @"C:\exports\quarter.docx";
            OfficeWorkflowViewHarness.Find<CheckBox>(view, "office.overwrite").IsChecked = true;

            OfficeWorkflowViewHarness.Find<Button>(view, "office.draft")
                .RaiseEvent(new RoutedEventArgs(Button.ClickEvent));

            var request = fixture.Connection.Sent.Single();
            Assert.AreEqual("office.job_request", request.CommandType);
            Assert.AreEqual("docx", ((NativeJsonString)request.Payload["format"]!).Value);
            Assert.AreEqual(@"C:\exports\quarter.docx", ((NativeJsonString)request.Payload["destination"]!).Value);
            Assert.IsTrue(((NativeJsonBoolean)request.Payload["overwrite_approved"]!).Value);
            var paragraphs = (NativeJsonArray)((NativeJsonObject)request.Payload["content"]!)["paragraphs"]!;
            Assert.AreEqual(2, paragraphs.Values.Count);
        });
    }

    [TestMethod]
    public async Task EditDraft_WritesPlainLanguageRequestWithoutSubmitting()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new OfficeView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            OfficeWorkflowViewHarness.Find<Expander>(view, "office.new-panel").IsExpanded = true;
            OfficeWorkflowViewHarness.Layout(view);
            OfficeWorkflowViewHarness.Find<TextBox>(view, "office.request").Text = "표 제목을 바꿔줘";

            OfficeWorkflowViewHarness.Find<Button>(view, "office.edit-draft")
                .RaiseEvent(new RoutedEventArgs(Button.ClickEvent));

            StringAssert.Contains(fixture.Model.OfficeWorkflow.Draft, "표 제목을 바꿔줘");
            Assert.AreEqual(0, fixture.Connection.Sent.Count);
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
            var action = OfficeWorkflowViewHarness.Find<Button>(shell, "office.draft");
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
