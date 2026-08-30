using System.Windows.Automation;
using System.Windows.Controls;
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
}
