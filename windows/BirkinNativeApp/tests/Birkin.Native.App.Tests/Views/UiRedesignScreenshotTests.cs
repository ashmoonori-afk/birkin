using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
public sealed class UiRedesignScreenshotTests
{
    [TestMethod]
    public async Task RepresentativeRoutes_WriteThreeOfflineViewportArtifacts()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var window = new MainWindow(fixture.Model, fixture.Coordinator)
            {
                ShowInTaskbar = false,
                WindowStyle = WindowStyle.None,
            };
            var view = OfficeWorkflowViewHarness.Snapshot(window);
            fixture.Model.PresentReadySnapshot(Snapshot(), () => { });
            view.Dispatcher.Invoke(() => { }, DispatcherPriority.DataBind);
            window.Show();
            try
            {
                var root = Path.GetFullPath(Path.Combine(
                    AppContext.BaseDirectory,
                    "..", "..", "..", "..", "..", "..", "..",
                    "reports", "ui-redesign-2026-09-08", "windows"));
                CaptureRoute(window, view, "route.research", 1500, 940,
                    Path.Combine(root, "windows-research-1500x940.png"));
                CaptureRoute(window, view, "route.documents", 1024, 768,
                    Path.Combine(root, "windows-documents-1024x768.png"));
                CaptureRoute(window, view, "route.approvals", 640, 760,
                    Path.Combine(root, "windows-approvals-640x760.png"));
            }
            finally
            {
                window.Close();
            }
            return true;
        });
    }

    private static void CaptureRoute(
        Window window,
        WorkspaceSnapshotView view,
        string route,
        int width,
        int height,
        string path)
    {
        window.Width = width;
        window.Height = height;
        view.ApplyAvailableWidth(width);
        OfficeWorkflowViewHarness.Find<Button>(view, route)
            .RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        view.Measure(new Size(width, height));
        view.Arrange(new Rect(0, 0, width, height));
        view.UpdateLayout();
        view.Dispatcher.Invoke(() => { }, DispatcherPriority.Render);
        var bitmap = new RenderTargetBitmap(width, height, 96, 96, PixelFormats.Pbgra32);
        bitmap.Render(view);
        var encoder = new PngBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(bitmap));
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        using var output = File.Create(path);
        encoder.Save(output);
        Assert.IsTrue(new FileInfo(path).Length > 10_000, path);
    }

    private static WorkspaceSnapshotPresentation Snapshot() => new(
        1,
        "분기 보고서 검토",
        27,
        "offline-ui-preview",
        "initial",
        "loopback",
        8,
        "connected",
        [
            new ConversationRowPresentation("u1", "user_message", "공식 원문을 확인해 핵심 차이를 조사해 주세요.", "user", 24),
            new ConversationRowPresentation("a1", "assistant_message", """
                # 조사 결과
                공식 문서의 직접 설명과 아직 확인하지 못한 항목을 구분했습니다.

                ## 확인한 원문
                > “The record is located on a separate line.”
                출처: https://www.rfc-editor.org/rfc/rfc4180

                ## 판단
                - 원문이 직접 뒷받침하는 범위만 결론에 포함했습니다.
                - 구현 선택은 제안이며 규격의 필연적 사실로 확정하지 않았습니다.

                ## 아직 답하지 못한 핵심 질문
                제품별 가져오기 동작은 추가 공식 문서가 필요합니다.
                """, "birkin", 25),
        ],
        new ComposerPresentation(true, false, false, true),
        new WorkingMemoryPresentation(4,
            [new WorkingMemoryRowPresentation("목표", ["공식 원문 검토"], "설정되지 않음")]),
        [new ApprovalPolicyRowPresentation("문서 변경", "office", "요청 시 확인", "기본값", false)],
        [new PanelItemPresentation(
            "approval-preview", "approval", "분기 보고서 변경 승인",
            "표의 합계 수식과 설명 문단을 바꿉니다.", "office", "medium",
            true, false, "분기보고서.xlsx", "검토본/분기보고서.xlsx", false,
            "offline-authority", "사용자")],
        [new PanelItemPresentation("activity-1", "office.diff_ready", "변경 내용 확인 준비", OfficePhase: "comparison")],
        [],
        [new PanelItemPresentation("office-1", "office.document", "분기보고서.xlsx", "가져온 문서 · 변경 검토 준비")],
        new TerminalPresentation(false, 0),
        MutationAvailabilityPresentation.PhaseOne,
        [new PanelItemPresentation("session-1", "session", "분기 보고서 검토", Status: "selected")],
        []);
}
