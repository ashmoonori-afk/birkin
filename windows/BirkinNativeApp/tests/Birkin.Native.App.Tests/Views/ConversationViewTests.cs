using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Documents;
using System.Windows.Threading;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class ConversationViewTests
{
    [TestMethod]
    public async Task Send_WhenAdvertised_PreservesExactMultilineDraftAndSubmitsOnce()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new ConversationView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            var draft = OfficeWorkflowViewHarness.Find<TextBox>(view, "conversation.draft");
            var send = OfficeWorkflowViewHarness.Find<Button>(view, "conversation.send");
            const string exactDraft = "  비교 요청\n둘째 줄  \n";
            draft.Text = exactDraft;

            // When
            send.RaiseEvent(new System.Windows.RoutedEventArgs(Button.ClickEvent));

            // Then
            Assert.AreEqual(1, fixture.Connection.Sent.Count);
            Assert.AreEqual("chat.send", fixture.Connection.Sent[0].CommandType);
            Assert.AreEqual(exactDraft, ((NativeJsonString)fixture.Connection.Sent[0].Payload["text"]!).Value);
            Assert.AreEqual("Send message", AutomationProperties.GetName(send));
            Assert.IsTrue(draft.AcceptsReturn);
        });
    }

    [TestMethod]
    public async Task Failure_WhenCommandFails_DoesNotExposeMachineCodeOrCursorInComposer()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        var test = await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            const string failureContext = "provider failure context";
            var refusal = OfficeWorkflowPresentation.Empty
                .WithDraft("retryable draft")
                .Begin("command-failed", "chat.send")
                .Refuse("command-failed", "E_COMMAND_FAILED", null, failureContext);
            var view = new ConversationView(fixture.Model, fixture.Coordinator);
            var window = new Window { Content = view, Width = 900, Height = 700 };
            window.Show();
            try
            {
                // When
                fixture.Model.PresentOfficeWorkflow(refusal);
                await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.DataBind);
                view.UpdateLayout();

                // Then
                _ = AutomationElement.FromHandle(new WindowInteropHelper(window).Handle);
                var primaryText = string.Join(" ", OfficeWorkflowViewHarness
                    .All<TextBlock>(view)
                    .Select(element => new TextRange(element.ContentStart, element.ContentEnd).Text));
                var failure = OfficeWorkflowViewHarness.Find<TextBlock>(view, "composer.failure");
                Assert.IsFalse(string.IsNullOrWhiteSpace(new TextRange(failure.ContentStart, failure.ContentEnd).Text));
                Assert.IsFalse(primaryText.Contains(failureContext, StringComparison.Ordinal));
                Assert.IsFalse(primaryText.Contains("E_COMMAND_FAILED", StringComparison.Ordinal));
                Assert.IsFalse(primaryText.Contains("E_CONNECTION_NOT_READY", StringComparison.Ordinal));
                Assert.IsFalse(primaryText.Contains("Cursor", StringComparison.Ordinal));
                Assert.AreEqual("E_COMMAND_FAILED", fixture.Model.OfficeWorkflow.RefusalCode);
                Assert.AreEqual("E_CONNECTION_NOT_READY", fixture.Model.OfficeWorkflow.Availability.ConversationSend.DisabledReason);
                Assert.IsNull(fixture.Model.OfficeWorkflow.CurrentCursor);
            }
            finally
            {
                window.Close();
            }
        });
        await test;
    }

    [TestMethod]
    public async Task EmptyConversation_WhenFailureWrapsAtMinimumWindowHeight_PreservesScrollableCaptionViewport()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        var test = await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync(emptyConversation: true);
            var refusal = OfficeWorkflowPresentation.Empty
                .WithDraft("retryable draft")
                .Begin("command-failed", "chat.send")
                .Refuse("command-failed", "E_COMMAND_FAILED", null, "diagnostic context");
            fixture.Model.PresentOfficeWorkflow(refusal);
            var window = new MainWindow(fixture.Model, fixture.Coordinator)
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
                // When
                await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.Render);
                window.UpdateLayout();

                // Then
                var conversationItems = OfficeWorkflowViewHarness.Find<ItemsControl>(window, "conversation.items");
                Assert.IsTrue(conversationItems.ActualHeight >= 105d,
                    $"empty conversation viewport was {conversationItems.ActualHeight}px");
            }
            finally
            {
                window.Close();
            }
        });
        await test;
    }

    [TestMethod]
    public async Task Rows_ExposeHumanLabelsWithoutAuthorityMetadata()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        // When / Then
        await sta.InvokeAsync(() =>
        {
            var view = new ConversationView
            {
                DataContext = new
                {
                    Workspace = new
                    {
                        Conversation = new[]
                        {
                            new { Kind = "user_message", Text = "Exact user text", ActorId = "native_human", Cursor = 41 },
                            new { Kind = "assistant_message", Text = "Exact Birkin text", ActorId = "python:authority", Cursor = 42 },
                            new { Kind = "assistant_stream", Text = "Streaming text", ActorId = "python:authority", Cursor = 43 },
                        },
                    },
                    OfficeWorkflow = new
                    {
                        CommandState = "Idle",
                        Availability = new { ConversationSend = new { IsEnabled = false, DisabledMessage = "Unavailable" } },
                        UserFacingFailure = (string?)null,
                    },
                },
            };
            OfficeWorkflowViewHarness.Layout(view);
            var items = OfficeWorkflowViewHarness.Find<ItemsControl>(view, "conversation.items");
            var labels = OfficeWorkflowViewHarness.All<TextBlock>(items)
                .Select(block => new TextRange(block.ContentStart, block.ContentEnd).Text.Trim())
                .Where(text => text is "You" or "Birkin" or "Message").ToArray();
            CollectionAssert.AreEqual(new[] { "You", "Birkin", "Birkin" }, labels);
            var presenters = OfficeWorkflowViewHarness.All<ContentPresenter>(items)
                .Where(presenter => presenter.Content is not null).ToArray();
            Assert.AreEqual(3, presenters.Length);
            foreach (var presenter in presenters)
            {
                var name = AutomationProperties.GetName(presenter);
                Assert.AreEqual("Conversation message", name);
                foreach (var forbidden in new[] { "ActorId", "Cursor =", "ConversationRowPresentation", "user_message", "assistant_message" })
                {
                    Assert.IsFalse(name.Contains(forbidden, StringComparison.OrdinalIgnoreCase), name);
                }
            }
            return Task.CompletedTask;
        });
    }

    [TestMethod]
    public async Task Draft_WhenStaleRefusalIsPresented_PreservesKoreanAndWhitespaceExactly()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            const string exactDraft = "  한글 초안\n둘째 줄  \n";
            var refusal = OfficeWorkflowPresentation.Empty
                .WithDraft(exactDraft)
                .Begin("command-stale", "chat.send")
                .Refuse("command-stale", "E_STALE_CURSOR", 41);
            var view = new ConversationView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);

            // When
            fixture.Model.PresentOfficeWorkflow(refusal);

            // Then
            Assert.AreEqual(exactDraft, OfficeWorkflowViewHarness.Find<TextBox>(view, "conversation.draft").Text);
            Assert.AreEqual(41L, fixture.Model.OfficeWorkflow.CurrentCursor);
            Assert.AreEqual("E_STALE_CURSOR", fixture.Model.OfficeWorkflow.RefusalCode);
        });
    }
}
