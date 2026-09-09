using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Shell;
using System.Windows.Threading;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
public sealed class MainWindowAttentionTests : MainWindowTestBase
{
    [TestMethod]
    public async Task Notification_WhenWindowLoadsLate_DefersFlashAndStopsOnClear()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        await sta.InvokeAsync(() =>
        {
            var window = new Window { Title = "Original title" };
            var flasher = new RecordingWindowFlasher();
            var toast = new RecordingApprovalToast();
            using var attention = new WindowsApprovalAttention(
                window,
                flasher,
                toast);
            attention.SetPending(1);
            attention.Notify(new ApprovalAttentionSignal("approval-1"));
            Assert.AreEqual(0, flasher.Starts);
            Assert.AreEqual(1, toast.Messages.Count);
            Assert.AreEqual("approval-1", toast.Messages[0].ApprovalId);
            Assert.AreEqual("approvals", toast.Messages[0].Route);
            Assert.AreEqual(0, toast.Messages[0].DecisionActions.Count);
            Assert.AreNotEqual("Original title", window.Title);

            window.Show();
            window.Dispatcher.Invoke(() => { }, DispatcherPriority.Loaded);
            Assert.AreEqual(1, flasher.Starts);

            attention.SetPending(0);
            Assert.AreEqual(1, flasher.Stops);
            Assert.AreEqual("Original title", window.Title);
            window.Close();
            return true;
        });
    }

    [TestMethod]
    public void ToastContent_WhenApprovalIsUntrusted_IsFixedAndNavigationOnly()
    {
        var content = ApprovalToastContent.For("opaque-approval-1");

        Assert.AreEqual("승인 요청이 도착했습니다", content.Title);
        Assert.AreEqual("Birkin에서 요청 내용을 확인하세요.", content.Body);
        Assert.AreEqual("opaque-approval-1", content.ApprovalId);
        Assert.AreEqual("approvals", content.Route);
        Assert.AreEqual(0, content.DecisionActions.Count);
    }

    [TestMethod]
    public void Toast_WhenSupportProbeCannotActivate_UsesFallback()
    {
        var toast = WindowsApprovalToast.Create(
            () => { },
            () => throw new COMException("activation unavailable"));

        Assert.IsNull(toast);
    }

    [TestMethod]
    public async Task Approval_WhenPending_MarksTaskbarUntilResolved()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        await sta.InvokeAsync(() =>
        {
            var model = new ShellPresentationModel(SynchronizationContext.Current!);
            var toast = new RecordingApprovalToast();
            var window = new MainWindow(model, toast);
            window.Show();
            model.PresentSnapshot(
                Snapshot([
                    new PanelItemPresentation("approval-1", "approval", "Untrusted"),
                ]),
                () => { });
            window.Dispatcher.Invoke(() => { }, DispatcherPriority.DataBind);

            Assert.IsNotNull(window.TaskbarItemInfo);
            Assert.AreEqual(1, toast.Messages.Count);
            Assert.AreEqual("approval-1", toast.Messages[0].ApprovalId);
            Assert.AreEqual(
                TaskbarItemProgressState.Paused,
                window.TaskbarItemInfo.ProgressState);

            model.PresentSnapshot(
                Snapshot([
                    new PanelItemPresentation(
                        "approval-1",
                        "approval",
                        "Untrusted",
                        Decided: true),
                ]),
                () => { });
            window.Dispatcher.Invoke(() => { }, DispatcherPriority.DataBind);

            Assert.AreEqual(
                TaskbarItemProgressState.None,
                window.TaskbarItemInfo.ProgressState);
            window.Close();
            return true;
        });
    }

    private static WorkspaceSnapshotPresentation Snapshot(
        IReadOnlyList<PanelItemPresentation> approvals) =>
        new(
            1,
            "notification-session",
            7,
            "0123456789abcdef0123456789abcdef",
            "event",
            "loopback",
            10,
            "connected",
            [],
            new ComposerPresentation(true, false, false, false),
            new WorkingMemoryPresentation(0, []),
            [],
            approvals,
            [],
            [],
            [],
            new TerminalPresentation(false, 0),
            MutationAvailabilityPresentation.PhaseOne);

    private sealed class RecordingWindowFlasher : IWindowFlasher
    {
        public int Starts { get; private set; }
        public int Stops { get; private set; }

        public void Start(nint window)
        {
            Assert.AreNotEqual(nint.Zero, window);
            Starts++;
        }

        public void Stop(nint window)
        {
            Assert.AreNotEqual(nint.Zero, window);
            Stops++;
        }
    }

    private sealed class RecordingApprovalToast : IApprovalToast
    {
        public List<ApprovalToastContent> Messages { get; } = [];

        public void Show(ApprovalToastContent content)
        {
            Messages.Add(content);
        }
    }
}
