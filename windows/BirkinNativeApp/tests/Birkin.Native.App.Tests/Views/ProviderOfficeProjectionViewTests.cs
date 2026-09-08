using System.IO;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class ProviderOfficeProjectionViewTests : MainWindowTestBase
{
    [TestMethod]
    public async Task MainWindow_RendersReadableConversationAttachmentAndHistoryLabels()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            var imported = new ImportedFilePresentation(
                "readability-file", "comparison-source.xlsx", "readability-file.xlsx",
                new string('a', 64), 128);
            var data = new
            {
                Workspace = new
                {
                    Conversation = new[]
                    {
                        new ConversationRowPresentation("message-1", "user_message", "비교해 주세요.", "user", 1),
                        new ConversationRowPresentation("message-2", "assistant_message", "비교 결과를 준비했습니다.", "birkin", 2),
                    },
                    RecentResults = new[]
                    {
                        new PanelItemPresentation("message-2", "assistant_message", "비교 결과를 준비했습니다."),
                    },
                    Sessions = Array.Empty<PanelItemPresentation>(),
                    WorkingMemory = new WorkingMemoryPresentation(0, []),
                    WorkItems = Array.Empty<PanelItemPresentation>(),
                },
                OfficeWorkflow = OfficeWorkflowPresentation.Empty with
                {
                    Imports = new[] { imported },
                },
            };
            var navigation = new NavigationColumnView { DataContext = data };
            var conversation = new ConversationView { DataContext = data };
            var surface = new Grid();
            surface.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(300) });
            surface.ColumnDefinitions.Add(new ColumnDefinition());
            Grid.SetColumn(conversation, 1);
            surface.Children.Add(navigation);
            surface.Children.Add(conversation);
            var window = new Window
            {
                Content = surface,
                Width = 1000,
                Height = 760,
                Background = (Brush)conversation.FindResource("CanvasBrush"),
                Foreground = (Brush)conversation.FindResource("TextBrush"),
            };
            window.Show();
            try
            {
                await window.Dispatcher.InvokeAsync(window.UpdateLayout);
                var visibleText = OfficeWorkflowViewHarness.DescendantsForTest<TextBlock>(window)
                    .Where(text => text.IsVisible)
                    .Select(text => text.Text)
                    .ToArray();
                CollectionAssert.Contains(visibleText, "사용자");
                CollectionAssert.Contains(visibleText, "Birkin");
                CollectionAssert.Contains(visibleText, "최근 결과 1개 · 활동 기록 보기");
                var attachment = OfficeWorkflowViewHarness.Find<CheckBox>(window, imported.ImportId);
                Assert.AreEqual(conversation.FindResource("TextBrush"), attachment.Foreground);
                Assert.IsTrue(attachment.IsVisible);
                var send = OfficeWorkflowViewHarness.Find<Button>(conversation, "conversation.send");
                var sendBounds = send.TransformToAncestor(surface).TransformBounds(
                    new Rect(0, 0, send.ActualWidth, send.ActualHeight));
                Assert.IsTrue(sendBounds.Height > 0);
                Assert.IsTrue(sendBounds.Bottom <= surface.RenderSize.Height);

                var evidenceRoot = Environment.GetEnvironmentVariable("BIRKIN_NATIVE_EVIDENCE_ROOT");
                if (!string.IsNullOrWhiteSpace(evidenceRoot))
                {
                    var width = (int)Math.Ceiling(surface.RenderSize.Width);
                    var height = (int)Math.Ceiling(surface.RenderSize.Height);
                    var bitmap = new RenderTargetBitmap(width, height, 96, 96, PixelFormats.Pbgra32);
                    bitmap.Render(surface);
                    var encoder = new PngBitmapEncoder();
                    encoder.Frames.Add(BitmapFrame.Create(bitmap));
                    var path = Path.Combine(evidenceRoot, "ui-readability", "conversation-history-attachment-final.png");
                    Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                    using var output = File.Create(path);
                    encoder.Save(output);
                    Assert.IsTrue(new FileInfo(path).Length > 0);
                }
            }
            finally
            {
                window.Close();
            }
        });
    }

    [TestMethod]
    public async Task MainWindow_ProjectsCanonicalDiffApprovalAndArtifactIntoVisibleControls()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        var journey = sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var window = new MainWindow(fixture.Model, fixture.Coordinator) { Width = 1500, Height = 940 };
            window.Show();
            try
            {
                fixture.ApplyCanonical("office.diff_ready", Object(
                    ("surface", Text("office")),
                    ("result", Object(("diff", Object(
                        ("diff_id", Text("diff-canonical")),
                        ("left", Text("4100")),
                        ("right", Text("4700"))))))));
                fixture.ApplyCanonical("approval.requested", Object(
                    ("approval_id", Text("approval-canonical")),
                    ("summary", Text("Canonical approval")),
                    ("sealed", new NativeJsonBoolean(true))));
                fixture.ApplyCanonical("office.updated", Object(
                    ("surface", Text("office")),
                    ("result", Object(("artifact", Object(
                        ("artifact_id", Text("artifact-canonical")),
                        ("media_type", Text("application/vnd.openxmlformats-officedocument.wordprocessingml.document"))))))));
                await window.Dispatcher.InvokeAsync(window.UpdateLayout);

                Assert.AreEqual(Visibility.Visible,
                    OfficeWorkflowViewHarness.Find<FrameworkElement>(window, "diff.landmark").Visibility);
                Assert.IsTrue(OfficeWorkflowViewHarness.Find<ItemsControl>(window, "diff.items")
                    .Items.Cast<object>().Any(item => item.ToString()!.Contains("4700", StringComparison.Ordinal)));
                var approve = OfficeWorkflowViewHarness.Find<Button>(
                    window,
                    "approval.approve.approval-canonical");
                Assert.AreEqual("approval-canonical", approve.Tag as string);
                Assert.IsTrue(OfficeWorkflowViewHarness.Find<ItemsControl>(window, "office.items")
                    .Items.Cast<object>().Any(item => item.ToString()!.Contains("artifact-canonical", StringComparison.Ordinal)));
            }
            finally
            {
                window.Close();
            }
        });
        await journey.WaitAsync(deadline.Token);
    }

    [TestMethod]
    public async Task MainWindow_RendersEditableWorkItemInitialValuesWithoutTwoWayBinding()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            var view = new NavigationColumnView
            {
                DataContext = new
                {
                    Workspace = new
                    {
                        WorkItems = new[]
                        {
                            new PanelItemPresentation(
                                "work-1", "work_item", "견적 검토",
                                Status: "예정", Assignee: "김담당", DueDate: "2026-09-12"),
                        },
                    },
                },
            };
            var window = new Window { Content = view, Width = 300, Height = 600 };
            window.Show();
            try
            {
                await window.Dispatcher.InvokeAsync(window.UpdateLayout);

                Assert.AreEqual("김담당", OfficeWorkflowViewHarness.Find<TextBox>(window, "work-item.assignee").Text);
                Assert.AreEqual(new DateTime(2026, 9, 12),
                    OfficeWorkflowViewHarness.Find<DatePicker>(window, "work-item.due-date").SelectedDate);
            }
            finally
            {
                window.Close();
            }
        });
    }

    [TestMethod]
    public async Task NavigationColumn_RendersCanonicalReceiptDetailWithAccessibleAction()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await using var workflow = await OfficeWorkflowViewHarness.CreateAsync();
        await sta.InvokeAsync(async () =>
        {
            var view = new NavigationColumnView
            {
                DataContext = new
                {
                    Workspace = new
                    {
                        WorkItems = new[]
                        {
                            new PanelItemPresentation(
                                "work-1", "work_item", "보고서 확인",
                                SourceType: "job_id", Target: "job-1",
                                SourceDetail: "분기 보고서를 저장했습니다.", SourceStatus: "exported",
                                SourceDestination: @"C:\approved\report.docx",
                                SourceValidation: "검증 통과"),
                        },
                    },
                },
            };
            var approvalFocusRequests = 0;
            var approvalFocused = new TaskCompletionSource(
                TaskCreationOptions.RunContinuationsAsynchronously);
            view.AttachWorkflow(
                workflow.Model,
                workflow.Coordinator,
                () => { },
                () =>
                {
                    approvalFocusRequests++;
                    approvalFocused.TrySetResult();
                });
            var window = new Window { Content = view, Width = 300, Height = 600 };
            window.Show();
            try
            {
                await window.Dispatcher.InvokeAsync(window.UpdateLayout);
                Assert.IsTrue(OfficeWorkflowViewHarness.DescendantsForTest<TextBlock>(window)
                    .Any(text => text.Text == "분기 보고서를 저장했습니다."));
                Assert.IsTrue(OfficeWorkflowViewHarness.DescendantsForTest<Button>(window)
                    .Any(button => AutomationProperties.GetName(button) == "결과 영수증 확인" && button.IsEnabled));
                var details = OfficeWorkflowViewHarness.Find<Expander>(window, "work-item.receipt-details");
                Assert.IsTrue(details.IsVisible);
                var action = OfficeWorkflowViewHarness.DescendantsForTest<Button>(window)
                    .Single(button => AutomationProperties.GetName(button) == "결과 영수증 확인");
                action.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                await window.Dispatcher.InvokeAsync(window.UpdateLayout);
                await workflow.ResolveLastAsync();
                Assert.IsTrue(details.IsExpanded);
                var textBrush = view.FindResource("TextBrush");
                var header = OfficeWorkflowViewHarness.DescendantsForTest<TextBlock>(details)
                    .Single(text => text.Text == "영수증 상세");
                var destination = OfficeWorkflowViewHarness.DescendantsForTest<TextBlock>(details)
                    .Single(text => text.Text == @"저장 위치: C:\approved\report.docx");
                Assert.AreEqual(textBrush, header.Foreground);
                Assert.AreEqual(textBrush, destination.Foreground);
                Assert.IsTrue(OfficeWorkflowViewHarness.DescendantsForTest<TextBlock>(details)
                    .Any(text => text.Text == "검증: 검증 통과"));
                var complete = OfficeWorkflowViewHarness.DescendantsForTest<Button>(window)
                    .Single(button => AutomationProperties.GetName(button) == "후속 업무 완료 승인 요청");
                complete.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                await approvalFocused.Task.WaitAsync(deadline.Token);
                Assert.AreEqual(1, approvalFocusRequests);
            }
            finally
            {
                window.Close();
            }
        });
    }

    private static NativeJsonString Text(string value) => new(value);

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));

}
