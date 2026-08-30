using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
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
            Assert.AreEqual("메시지 보내기", AutomationProperties.GetName(send));
            Assert.IsTrue(draft.AcceptsReturn);
        });
    }

    [TestMethod]
    public async Task Stop_WhenTurnIsInterruptible_SubmitsCanonicalInterruptOnce()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync(
                canInterrupt: true);
            var view = new ConversationView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            var stop = OfficeWorkflowViewHarness.Find<Button>(
                view,
                "conversation.stop");
            var actions = OfficeWorkflowViewHarness.Find<StackPanel>(
                view,
                "conversation.actions");

            Assert.IsTrue(stop.IsEnabled);
            Assert.AreEqual(1D, stop.Opacity);
            Assert.AreEqual("응답 중지", AutomationProperties.GetName(stop));
            CollectionAssert.AreEqual(
                new[] { "conversation.stop", "conversation.send" },
                actions.Children
                    .Cast<DependencyObject>()
                    .Select(AutomationProperties.GetAutomationId)
                    .ToArray());

            stop.RaiseEvent(new System.Windows.RoutedEventArgs(Button.ClickEvent));

            Assert.AreEqual(1, fixture.Connection.Sent.Count);
            Assert.AreEqual("chat.interrupt", fixture.Connection.Sent[0].CommandType);
            Assert.AreEqual(0, fixture.Connection.Sent[0].Payload.Count);
        });
    }

    [TestMethod]
    public async Task Stop_WhenTurnIsIdle_IsVisiblyDisabled()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new ConversationView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            var stop = OfficeWorkflowViewHarness.Find<Button>(
                view,
                "conversation.stop");

            Assert.IsFalse(stop.IsEnabled);
            Assert.AreEqual(0.68D, stop.Opacity, 0.001D);
        });
    }

    [TestMethod]
    public async Task Send_WhenCanonicalTurnCompletes_RestoresDraftKeyboardFocus()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new ConversationView(fixture.Model, fixture.Coordinator);
            var window = new Window { Content = view };
            window.Show();
            OfficeWorkflowViewHarness.Layout(view);
            var draft = OfficeWorkflowViewHarness.Find<TextBox>(
                view,
                "conversation.draft");
            var send = OfficeWorkflowViewHarness.Find<Button>(
                view,
                "conversation.send");
            draft.Text = "focus after completion";
            Assert.IsTrue(send.Focus());

            send.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            await fixture.ResolveLastAsync();
            view.Dispatcher.Invoke(
                () => { },
                System.Windows.Threading.DispatcherPriority.ContextIdle);

            Assert.AreSame(draft, Keyboard.FocusedElement);
            window.Close();
        });
    }

    [TestMethod]
    public async Task CtrlEnter_WhenKoreanCompositionCommits_SendsWithoutPrematureMutation()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new ConversationView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            var draft = OfficeWorkflowViewHarness.Find<TextBox>(
                view,
                "conversation.draft");
            const string exactDraft = "  한글 조합\n둘째 줄  ";
            draft.Text = exactDraft;

            var composition = new TextComposition(
                InputManager.Current,
                draft,
                "한글");
            draft.RaiseEvent(new TextCompositionEventArgs(
                Keyboard.PrimaryDevice,
                composition)
            {
                RoutedEvent = TextCompositionManager.PreviewTextInputStartEvent,
            });
            Assert.IsFalse(await view.HandleDraftKeyAsync(
                Key.Enter,
                ModifierKeys.Control));
            Assert.IsFalse(await view.HandleDraftKeyAsync(
                Key.Enter,
                ModifierKeys.None));
            Assert.AreEqual(exactDraft, draft.Text);
            Assert.AreEqual(0, fixture.Connection.Sent.Count);

            draft.RaiseEvent(new TextCompositionEventArgs(
                Keyboard.PrimaryDevice,
                composition)
            {
                RoutedEvent = TextCompositionManager.PreviewTextInputEvent,
            });
            Assert.IsTrue(await view.HandleDraftKeyAsync(
                Key.Enter,
                ModifierKeys.Control));

            Assert.AreEqual(1, fixture.Connection.Sent.Count);
            Assert.AreEqual("chat.send", fixture.Connection.Sent[0].CommandType);
            Assert.AreEqual(
                exactDraft,
                ((NativeJsonString)fixture.Connection.Sent[0].Payload["text"]!).Value);
        });
    }

    [TestMethod]
    public void SendKeyPolicy_RequiresCtrlEnterAfterCompositionEnds()
    {
        Assert.IsFalse(WindowsSendKeyPolicy.ShouldSend(
            Key.Enter,
            ModifierKeys.Control,
            hasMarkedText: true));
        Assert.IsTrue(WindowsSendKeyPolicy.ShouldSend(
            Key.Enter,
            ModifierKeys.Control,
            hasMarkedText: false));
        Assert.IsFalse(WindowsSendKeyPolicy.ShouldSend(
            Key.Enter,
            ModifierKeys.None,
            hasMarkedText: false));
        Assert.IsFalse(WindowsSendKeyPolicy.ShouldSend(
            Key.ImeProcessed,
            ModifierKeys.Control,
            hasMarkedText: false));
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
                .Refuse(
                    "command-stale",
                    "E_STALE_CURSOR",
                    "cursor is stale",
                    false,
                    41);
            var view = new ConversationView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);

            // When
            fixture.Model.PresentOfficeWorkflow(refusal);

            // Then
            Assert.AreEqual(exactDraft, OfficeWorkflowViewHarness.Find<TextBox>(view, "conversation.draft").Text);
            Assert.AreEqual(41L, fixture.Model.OfficeWorkflow.CurrentCursor);
            Assert.AreEqual("E_STALE_CURSOR", fixture.Model.OfficeWorkflow.RefusalCode);
            Assert.AreEqual(
                "작업 상태가 이미 변경되었습니다. 최신 내용을 확인한 뒤 다시 시도하세요.",
                OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "conversation.refusal").Text);
            Assert.AreEqual(
                "요청이 거부되었습니다.",
                OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "conversation.command-state").Text);
        });
    }

    [TestMethod]
    public async Task CommandProgress_WhenPending_ShowsKoreanCopyAndAnimatedSpinner()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new ConversationView(fixture.Model, fixture.Coordinator);
            var window = new Window { Content = view };
            window.Show();

            try
            {
                OfficeWorkflowViewHarness.Layout(view);
                fixture.Model.PresentOfficeWorkflow(
                    OfficeWorkflowPresentation.Empty.Begin(
                        "command-progress",
                        "chat.send"));
                view.Dispatcher.Invoke(
                    () => { },
                    System.Windows.Threading.DispatcherPriority.ContextIdle);

                var progress = OfficeWorkflowViewHarness.Find<StackPanel>(
                    view,
                    "conversation.command-progress");
                var label = OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "conversation.command-progress-label");
                var spinner = OfficeWorkflowViewHarness.Find<Path>(
                    view,
                    "conversation.command-progress-spinner");

                Assert.AreEqual(
                    System.Windows.Visibility.Visible,
                    progress.Visibility);
                Assert.AreEqual("명령을 전송하고 있습니다.", label.Text);
                Assert.IsInstanceOfType<RotateTransform>(
                    spinner.RenderTransform);
                Assert.IsTrue(
                    spinner.RenderTransform.HasAnimatedProperties);
            }
            finally
            {
                window.Close();
            }
        });
    }
}
