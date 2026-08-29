using System.IO;
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

    [TestMethod]
    public async Task AnsweredApproval_WhenCanonicalResolutionArrives_RemovesActionableCard()
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

    private static string RepositoryRoot()
    {
        for (
            var directory = new DirectoryInfo(Directory.GetCurrentDirectory());
            directory is not null;
            directory = directory.Parent)
        {
            if (Directory.Exists(Path.Combine(directory.FullName, ".git")))
            {
                return directory.FullName;
            }
        }
        throw new InvalidOperationException("repository root was not found");
    }
}
