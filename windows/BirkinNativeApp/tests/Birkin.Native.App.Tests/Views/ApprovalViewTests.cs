using System.IO;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class ApprovalViewTests
{
    [TestMethod]
    public void ConfirmationMessage_IncludesDestinationAndOverwriteVerdict()
    {
        // Given
        var card = new PanelItemPresentation(
            "approval-7",
            "approval",
            "Approve reviewed workbook",
            Destination: "C:\\Exports\\quarterly.xlsx",
            OverwriteApproved: true);

        // When
        var message = ApprovalView.ConfirmationMessage(
            card,
            "승인",
            "저장 위치 없음");

        // Then
        StringAssert.Contains(message, "승인하시겠습니까?");
        StringAssert.Contains(message, "C:\\Exports\\quarterly.xlsx");
        StringAssert.Contains(message, "주의: 기존 파일을 덮어쓸 수 있습니다");
    }

    [DataTestMethod]
    [DataRow("create", "후속 업무 생성")]
    [DataRow("update", "후속 업무 수정")]
    [DataRow("complete", "후속 업무 완료")]
    public void WorkItemConfirmation_ShowsReviewContentWithoutFileLanguage(
        string approvalAction,
        string expectedChange)
    {
        var card = new PanelItemPresentation(
            "4dba63e5beed",
            "approval",
            "후속 업무 생성 확인",
            "업무: 검증 보고서 확인 · 담당자: 검증 담당 · 기한: 2050-01-01",
            Category: "work_item",
            ApprovalAction: approvalAction);

        var message = ApprovalView.ConfirmationMessage(
            card,
            "승인",
            "저장 위치 없음");

        StringAssert.Contains(message, card.Description);
        StringAssert.Contains(message, expectedChange);
        Assert.IsFalse(message.Contains("저장 위치", StringComparison.Ordinal));
        Assert.IsFalse(message.Contains("덮어쓰기", StringComparison.Ordinal));
    }

    [TestMethod]
    public async Task AnsweredApproval_WhenCanonicalResolutionArrives_MovesToDecidedHistory()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new ApprovalView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            Assert.AreEqual(1, view.ApprovalRows.Count);

            // When
            fixture.ApplyCanonical(
                "approval.answered",
                new NativeJsonObject([
                    new("approval_id", new NativeJsonString("approval-7")),
                    new("decision", new NativeJsonString("approve")),
                    new("outcome", new NativeJsonString("approved")),
                    new("receipt", new NativeJsonString("receipt:approval-7")),
                ]));

            // Then
            Assert.AreEqual(0, view.ApprovalRows.Count);
            var decided = view.DecidedApprovalRows.Single();
            Assert.AreEqual("승인됨", decided.OutcomeLabel);
            Assert.AreEqual("receipt:approval-7", decided.ReceiptRef);
        });
    }

    [TestMethod]
    public async Task TrustDetails_WhenOfficeApprovalIsVisible_RenderCanonicalAuthorityContext()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();

            // When
            var view = new ApprovalView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);

            // Then
            Assert.AreEqual("승인", view.FindResource("ApprovalApproveLabel"));
            Assert.AreEqual("거부", view.FindResource("ApprovalRejectLabel"));
            Assert.AreEqual(
                "승인 결정 확인",
                view.FindResource("ApprovalConfirmTitle"));
            Assert.AreEqual(
                "승인",
                view.FindResource("ApprovalConfirmApproveAction"));
            Assert.AreEqual(
                "거부",
                view.FindResource("ApprovalConfirmRejectAction"));
            Assert.AreEqual(
                "Comparison!A1 변경: 4100 → 4700",
                OfficeWorkflowViewHarness.Find<TextBlock>(view, "approval.description.approval-7").Text);
            var destination = OfficeWorkflowViewHarness.Find<TextBlock>(
                view,
                "approval.destination.approval-7");
            StringAssert.Contains(destination.Text, "comparison-report.xlsx");
            Assert.AreEqual(
                @"C:\workspace\approved\comparison-report.xlsx",
                destination.ToolTip);
            Assert.AreEqual(
                "안전: 기존 파일이 없어야 합니다",
                OfficeWorkflowViewHarness.Find<TextBlock>(view, "approval.overwrite.approval-7").Text);
            Assert.AreEqual(
                "높은 위험",
                OfficeWorkflowViewHarness.Find<TextBlock>(view, "approval.risk.approval-7").Text);
            Assert.AreEqual(
                "검토 내용 고정됨",
                OfficeWorkflowViewHarness.Find<TextBlock>(view, "approval.sealed.approval-7").Text);
            Assert.AreEqual(
                "comparison-source.xlsx",
                OfficeWorkflowViewHarness.Find<TextBlock>(view, "approval.source.approval-7").Text);
            Assert.AreEqual(
                "요청자: native:office-journey",
                OfficeWorkflowViewHarness.Find<TextBlock>(view, "approval.requester.approval-7").Text);
            Assert.AreEqual(
                "거부하면 원본은 변경되지 않으며 새 파일도 저장되지 않습니다.",
                OfficeWorkflowViewHarness.Find<TextBlock>(view, "approval.rejection.approval-7").Text);
        });
    }

    [TestMethod]
    public async Task TrustCard_WhenRendered_WritesScreenshotArtifact()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new ApprovalView(fixture.Model, fixture.Coordinator);
            const int width = 360;
            const int height = 540;
            view.Measure(new System.Windows.Size(width, height));
            view.Arrange(new System.Windows.Rect(0, 0, width, height));
            view.UpdateLayout();
            var bitmap = new RenderTargetBitmap(
                width,
                height,
                96,
                96,
                PixelFormats.Pbgra32);
            bitmap.Render(view);
            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(bitmap));
            var path = EvidencePath();
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);

            // When
            using (var output = File.Create(path))
            {
                encoder.Save(output);
            }

            // Then
            var pixels = new byte[width * height * 4];
            bitmap.CopyPixels(pixels, width * 4, 0);
            var opaquePixels = 0;
            var colors = new HashSet<int>();
            for (var index = 0; index < pixels.Length; index += 4)
            {
                if (pixels[index + 3] != 0)
                {
                    opaquePixels++;
                }
                _ = colors.Add(BitConverter.ToInt32(pixels, index));
            }
            Assert.IsTrue(opaquePixels > width * height / 3);
            Assert.IsTrue(colors.Count > 12);
            Assert.IsTrue(new FileInfo(path).Length > 1_000);
        });
    }

    [TestMethod]
    public async Task Approve_WhenProjectedApprovalIsVisible_SubmitsItsCanonicalIdOnce()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new ApprovalView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            var approve = OfficeWorkflowViewHarness.Find<Button>(view, "approval.approve.approval-7");
            var confirmations = 0;
            view.ConfirmDecision = (card, decision) =>
            {
                confirmations++;
                Assert.AreEqual("approval-7", card.Id);
                Assert.AreEqual(ApprovalDecision.Approve, decision);
                return true;
            };

            // When
            approve.RaiseEvent(new System.Windows.RoutedEventArgs(Button.ClickEvent));

            // Then
            Assert.AreEqual(1, fixture.Connection.Sent.Count);
            Assert.AreEqual("approval.answer", fixture.Connection.Sent[0].CommandType);
            Assert.AreEqual("approval-7", ((NativeJsonString)fixture.Connection.Sent[0].Payload["approval_id"]!).Value);
            Assert.AreEqual("approve", ((NativeJsonString)fixture.Connection.Sent[0].Payload["decision"]!).Value);
            Assert.AreEqual(1, confirmations);
            Assert.AreEqual("요청한 작업 승인", AutomationProperties.GetName(approve));
        });
    }

    [TestMethod]
    public async Task Approve_WhenConfirmationIsCancelled_DoesNotSubmit()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new ApprovalView(fixture.Model, fixture.Coordinator)
            {
                ConfirmDecision = (_, _) => false,
            };
            OfficeWorkflowViewHarness.Layout(view);
            var approve = OfficeWorkflowViewHarness.Find<Button>(
                view,
                "approval.approve.approval-7");

            // When
            approve.RaiseEvent(new System.Windows.RoutedEventArgs(Button.ClickEvent));

            // Then
            Assert.AreEqual(0, fixture.Connection.Sent.Count);
        });
    }

    [TestMethod]
    public async Task UnknownMailSend_WhenRecheckable_RemainsVisibleAndSendsRecheckOnly()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            fixture.ApplyCanonical("workspace.refreshed", Object(
                ("approval_requests", new NativeJsonArray([
                    Object(
                        ("id", Text("a1b2c3d4e5f6")),
                        ("kind", Text("approval")),
                        ("summary", Text("메일 발송 상태 확인")),
                        ("category", Text("mail_send")),
                        ("risk", Text("high")),
                        ("sealed", new NativeJsonBoolean(true)),
                        ("draft_id", Text("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")),
                        ("content_sha256", Text("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")),
                        ("status", Text("action_outcome_unknown")),
                        ("ui_state", Text("action_needed")),
                        ("decided", new NativeJsonBoolean(true)),
                        ("recheckable", new NativeJsonBoolean(true))),
                    Object(
                        ("id", Text("b1c2d3e4f5a6")),
                        ("kind", Text("approval")),
                        ("summary", Text("메일 발송 요청 접수")),
                        ("category", Text("mail_send")),
                        ("risk", Text("high")),
                        ("sealed", new NativeJsonBoolean(true)),
                        ("draft_id", Text("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")),
                        ("content_sha256", Text("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")),
                        ("status", Text("action_outcome_unknown")),
                        ("ui_state", Text("action_needed")),
                        ("decided", new NativeJsonBoolean(true)),
                        ("recheckable", new NativeJsonBoolean(true)),
                        ("mail_recheck_state", Text("accepted")))
                ]))));
            var view = new ApprovalView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view, width: 380, height: 880);

            Assert.AreEqual(2, view.ApprovalRows.Count);
            Assert.AreEqual(0, view.DecidedApprovalRows.Count);
            Assert.AreEqual(
                "현재 원격 발송 상태를 확인할 수 없음",
                OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "approval.recheck-state.a1b2c3d4e5f6").Text);
            Assert.AreEqual(
                "실행 결과 확인 필요",
                view.ApprovalRows.Single(item => item.Id == "a1b2c3d4e5f6").OutcomeLabel);
            Assert.AreEqual(
                "Microsoft 365가 요청을 접수함 · 발송 처리는 아직 확인되지 않음",
                OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "approval.recheck-state.b1c2d3e4f5a6").Text);
            var recheck = OfficeWorkflowViewHarness.Find<Button>(
                view,
                "approval.recheck.a1b2c3d4e5f6");
            Assert.AreEqual(Visibility.Visible, recheck.Visibility);
            Assert.IsTrue(recheck.IsEnabled);
            Assert.AreEqual("발송 상태 다시 확인", AutomationProperties.GetName(recheck));
            Assert.IsFalse(
                OfficeWorkflowViewHarness.Find<Button>(
                    view,
                    "approval.approve.a1b2c3d4e5f6").IsVisible);
            var outcome = OfficeWorkflowViewHarness.Find<TextBlock>(
                view,
                "approval.outcome.a1b2c3d4e5f6");
            Assert.AreEqual(Visibility.Collapsed, ((FrameworkElement)outcome.Parent).Visibility);
            var state = OfficeWorkflowViewHarness.Find<TextBlock>(
                view,
                "approval.recheck-state.a1b2c3d4e5f6");
            var stateBounds = state.TransformToAncestor(view).TransformBounds(
                new Rect(0, 0, state.ActualWidth, state.ActualHeight));
            var buttonBounds = recheck.TransformToAncestor(view).TransformBounds(
                new Rect(0, 0, recheck.ActualWidth, recheck.ActualHeight));
            Assert.IsTrue(stateBounds.Height > 0);
            Assert.IsTrue(buttonBounds.Height > 0);
            Assert.IsTrue(stateBounds.Bottom <= buttonBounds.Top);
            Assert.IsTrue(buttonBounds.Right <= view.ActualWidth);
            Assert.IsTrue(buttonBounds.Bottom <= view.ActualHeight);

            recheck.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            await view.Dispatcher.InvokeAsync(() => { });

            var request = fixture.Connection.Sent.Single();
            Assert.AreEqual("approval.recheck", request.CommandType);
            CollectionAssert.AreEqual(new[] { "approval_id" }, request.Payload.Keys.ToArray());
            Assert.AreEqual(
                "a1b2c3d4e5f6",
                ((NativeJsonString)request.Payload["approval_id"]!).Value);
        });
    }

    [TestMethod]
    public async Task UnknownApproval_WhenNotRecheckable_DoesNotExposeMailRecheckAction()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            fixture.ApplyCanonical("workspace.refreshed", Object(
                ("approval_requests", new NativeJsonArray([
                    Object(
                        ("id", Text("c1d2e3f4a5b6")),
                        ("kind", Text("approval")),
                        ("summary", Text("메일 검토 필요")),
                        ("category", Text("mail_send")),
                        ("risk", Text("high")),
                        ("sealed", new NativeJsonBoolean(true)),
                        ("draft_id", Text("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")),
                        ("content_sha256", Text("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")),
                        ("status", Text("action_outcome_unknown")),
                        ("ui_state", Text("action_needed")),
                        ("decided", new NativeJsonBoolean(true)),
                        ("recheckable", new NativeJsonBoolean(false)),
                        ("mail_recheck_state", Text("needs_review"))),
                    Object(
                        ("id", Text("d1e2f3a4b5c6")),
                        ("kind", Text("approval")),
                        ("summary", Text("명령 상태 불명")),
                        ("category", Text("shell")),
                        ("status", Text("action_outcome_unknown")),
                        ("ui_state", Text("action_needed")),
                        ("decided", new NativeJsonBoolean(true)),
                        ("recheckable", new NativeJsonBoolean(true)))
                ]))));
            var view = new ApprovalView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);

            Assert.AreEqual("c1d2e3f4a5b6", view.ApprovalRows.Single().Id);
            Assert.AreEqual("d1e2f3a4b5c6", view.DecidedApprovalRows.Single().Id);

            Assert.AreEqual(
                "연결 계정 또는 승인 내용을 확인할 수 없어 검토가 필요합니다",
                OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "approval.recheck-state.c1d2e3f4a5b6").Text);
            Assert.AreEqual(
                Visibility.Collapsed,
                OfficeWorkflowViewHarness.Find<Button>(
                    view,
                    "approval.recheck.c1d2e3f4a5b6").Visibility);
            Assert.AreEqual(
                0,
                OfficeWorkflowViewHarness.FindAll<Button>(
                    view,
                    "approval.recheck.d1e2f3a4b5c6").Count);
            Assert.AreEqual(
                0,
                OfficeWorkflowViewHarness.FindAll<TextBlock>(
                    view,
                    "approval.recheck-state.d1e2f3a4b5c6").Count);
            Assert.AreEqual(
                "실행 결과 확인 필요",
                view.DecidedApprovalRows.Single(item => item.Id == "d1e2f3a4b5c6").OutcomeLabel);
        });
    }

    [TestMethod]
    public async Task AcceptedUnknownMail_WhenRenderedAtNarrowWidth_WritesReviewArtifact()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            fixture.ApplyCanonical("workspace.refreshed", Object(
                ("approval_requests", new NativeJsonArray([
                    Object(
                        ("id", Text("b1c2d3e4f5a6")),
                        ("kind", Text("approval")),
                        ("summary", Text("메일 발송 요청 접수")),
                        ("category", Text("mail_send")),
                        ("risk", Text("high")),
                        ("sealed", new NativeJsonBoolean(true)),
                        ("draft_id", Text("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")),
                        ("content_sha256", Text("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")),
                        ("status", Text("action_outcome_unknown")),
                        ("ui_state", Text("action_needed")),
                        ("decided", new NativeJsonBoolean(true)),
                        ("recheckable", new NativeJsonBoolean(true)),
                        ("mail_recheck_state", Text("accepted")),
                        ("mail_rechecked_at", Text("2026-09-08T03:00:00+00:00")))
                ]))));
            var view = new ApprovalView(fixture.Model, fixture.Coordinator);
            const int width = 380;
            const int height = 540;
            OfficeWorkflowViewHarness.Layout(view, width, height);
            Assert.IsTrue(OfficeWorkflowViewHarness.Find<Button>(
                view,
                "approval.recheck.b1c2d3e4f5a6").IsEnabled);
            Assert.AreEqual(
                0,
                OfficeWorkflowViewHarness.FindAll<TextBlock>(
                    view,
                    "approval.rejection.b1c2d3e4f5a6").Count(element => element.IsVisible));
            var bitmap = new RenderTargetBitmap(width, height, 96, 96, PixelFormats.Pbgra32);
            bitmap.Render(view);
            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(bitmap));
            var path = MailRecheckEvidencePath();
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            using var output = File.Create(path);
            encoder.Save(output);

            Assert.IsTrue(new FileInfo(path).Length > 0);
            Assert.AreEqual("b1c2d3e4f5a6", view.ApprovalRows.Single().Id);
            Assert.AreEqual(0, view.DecidedApprovalRows.Count);
        });
    }

    [TestMethod]
    public void SubmittedMailOutcome_DoesNotClaimRecipientDelivery()
    {
        var card = new PanelItemPresentation(
            "approval-mail-2",
            "approval",
            "메일 발송",
            Category: "mail_send",
            Decided: true,
            Status: "approved",
            MailRecheckState: "submitted");

        Assert.AreEqual(
            "Microsoft 365 발송 처리 확인 · 수신자 배달 완료는 확인하지 않음",
            card.OutcomeLabel);
        Assert.AreEqual("메일 발송", card.CategoryLabel);
        Assert.IsFalse(card.OutcomeLabel.Contains("수신자 배달 완료됨", StringComparison.Ordinal));
    }

    [TestMethod]
    public async Task SubmittedMailProjection_MovesToDecidedHistory()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            fixture.ApplyCanonical("workspace.refreshed", Object(
                ("approval_requests", new NativeJsonArray([
                    Object(
                        ("id", Text("e1f2a3b4c5d6")),
                        ("kind", Text("approval")),
                        ("summary", Text("메일 발송 처리 확인")),
                        ("category", Text("mail_send")),
                        ("risk", Text("high")),
                        ("sealed", new NativeJsonBoolean(true)),
                        ("draft_id", Text("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")),
                        ("content_sha256", Text("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")),
                        ("status", Text("approved")),
                        ("ui_state", Text("succeeded")),
                        ("decided", new NativeJsonBoolean(true)),
                        ("recheckable", new NativeJsonBoolean(false)),
                        ("mail_recheck_state", Text("submitted")))
                ]))));
            var view = new ApprovalView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view, width: 380, height: 880);

            Assert.AreEqual(0, view.ApprovalRows.Count);
            var decided = view.DecidedApprovalRows.Single();
            Assert.AreEqual("e1f2a3b4c5d6", decided.Id);
            Assert.AreEqual(
                "Microsoft 365 발송 처리 확인 · 수신자 배달 완료는 확인하지 않음",
                decided.OutcomeLabel);
        });
    }

    [DataTestMethod]
    [DataRow(null, "현재 원격 발송 상태를 확인할 수 없음")]
    [DataRow("accepted", "Microsoft 365가 요청을 접수함 · 발송 처리는 아직 확인되지 않음")]
    [DataRow("needs_review", "연결 계정 또는 승인 내용을 확인할 수 없어 검토가 필요합니다")]
    [DataRow("submitted", "Microsoft 365 발송 처리 확인 · 수신자 배달 완료는 확인하지 않음")]
    public void MailRecheckState_UsesBoundedStatusCopy(string? state, string expected)
    {
        Assert.AreEqual(expected, KoreanDecisionText.MailRecheck(state));
    }

    [TestMethod]
    public async Task DecidedReceipt_WhenExportCompleted_RendersCollapsedTrustCard()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            fixture.ApplyCanonical("approval.answered", Object(
                ("approval_id", Text("approval-7")),
                ("decision", Text("approve")),
                ("outcome", Text("approved")),
                ("summary", Text("Office export completed")),
                ("destination", Text("C:\\workspace\\approved.xlsx")),
                ("receipt_ref", Text("office:job-7")),
                ("expires_at", Text("2099-09-28T12:00:00+00:00")),
                ("backup_exists", new NativeJsonBoolean(true)),
                ("validation_summary", Text("등록된 구조 검증 통과")),
                ("visual_validation_summary", Text("시각 검증 미실행"))));
            var view = new ApprovalView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);

            Assert.AreEqual(0, view.ApprovalRows.Count);
            var decided = view.DecidedApprovalRows.Single();
            Assert.AreEqual("office:job-7", decided.ReceiptRef);
            Assert.AreEqual("C:\\workspace\\approved.xlsx", decided.Destination);
            Assert.AreEqual(
                "원본은 백업되었으며 9월 28일까지 되돌리기 가능",
                decided.RollbackAvailabilityLabel);
            var section = OfficeWorkflowViewHarness.Find<Expander>(
                view,
                "approval.decided.section");
            Assert.IsFalse(section.IsExpanded);
            section.IsExpanded = true;
            OfficeWorkflowViewHarness.Layout(view);
            Assert.AreEqual(
                "C:\\workspace\\approved.xlsx",
                OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "approval.receipt.destination.approval-7").Text);
            Assert.AreEqual(
                decided.RollbackAvailabilityLabel,
                OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "approval.receipt.retention.approval-7").Text);
            Assert.AreEqual(
                "승인됨",
                OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "approval.outcome.approval-7").Text);
            Assert.AreEqual(
                "office:job-7",
                OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "approval.receipt-reference.approval-7").Text);
            Assert.IsNotNull(
                OfficeWorkflowViewHarness.Find<Button>(
                    view,
                    "approval.receipt.open-file.approval-7"));
            Assert.IsNotNull(
                OfficeWorkflowViewHarness.Find<Button>(
                    view,
                    "approval.receipt.open-folder.approval-7"));
            Assert.AreEqual(
                "등록된 구조 검증 통과",
                OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "approval.receipt.validation.approval-7").Text);
            Assert.AreEqual(
                "시각 검증 미실행",
                OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "approval.receipt.visual-validation.approval-7").Text);
            OfficeWorkflowViewHarness.Find<Button>(
                view,
                "approval.receipt.follow-up.approval-7").RaiseEvent(
                    new RoutedEventArgs(Button.ClickEvent));
            StringAssert.Contains(
                fixture.Model.OfficeWorkflow.Draft,
                "C:\\workspace\\approved.xlsx");
        });
    }

    [TestMethod]
    public async Task RollbackButton_WhenReceiptSelected_SendsReceiptReferenceOnly()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            fixture.ApplyCanonical("approval.answered", Object(
                ("approval_id", Text("approval-7")),
                ("decision", Text("approve")),
                ("outcome", Text("approved")),
                ("summary", Text("Office export completed")),
                ("destination", Text("C:\\workspace\\approved.xlsx")),
                ("receipt_ref", Text("office:job-7")),
                ("expires_at", Text("2099-09-28T12:00:00+00:00")),
                ("backup_exists", new NativeJsonBoolean(true))));
            var view = new ApprovalView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            OfficeWorkflowViewHarness.Find<Expander>(
                view,
                "approval.decided.section").IsExpanded = true;
            OfficeWorkflowViewHarness.Layout(view);

            OfficeWorkflowViewHarness.Find<Button>(
                view,
                "approval.receipt.rollback.approval-7").RaiseEvent(
                    new RoutedEventArgs(Button.ClickEvent));
            await view.Dispatcher.InvokeAsync(() => { });

            var request = fixture.Connection.Sent[^1];
            Assert.AreEqual("office.rollback_request", request.CommandType);
            CollectionAssert.AreEquivalent(
                new[] { "receipt_ref" },
                request.Payload.Keys.ToArray());
            Assert.AreEqual(
                "office:job-7",
                ((NativeJsonString)request.Payload["receipt_ref"]!).Value);
            Assert.IsFalse(request.Payload.ContainsKey("job_id"));
        });
    }

    private static NativeJsonString Text(string value) => new(value);

    private static NativeJsonObject Object(
        params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair =>
            new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));

    private static string EvidencePath()
    {
        var workspace = Environment.GetEnvironmentVariable("GITHUB_WORKSPACE");
        var root = string.IsNullOrWhiteSpace(workspace)
            ? RepositoryRoot()
            : workspace;
        return Path.Combine(
            root,
            ".omo",
            "evidence",
            "native-shell",
            "windows-approval-trust-card.png");
    }

    private static string MailRecheckEvidencePath() => Path.Combine(
        RepositoryRoot(),
        "reports",
        "mail-recheck-ui-evidence",
        "unknown-mail-accepted-380px.png");

    private static string RepositoryRoot()
    {
        for (
            var directory = new DirectoryInfo(Directory.GetCurrentDirectory());
            directory is not null;
            directory = directory.Parent)
        {
            if (Directory.Exists(Path.Combine(directory.FullName, ".git"))
                || File.Exists(Path.Combine(directory.FullName, ".git")))
            {
                return directory.FullName;
            }
        }
        throw new InvalidOperationException("repository root was not found");
    }
}
