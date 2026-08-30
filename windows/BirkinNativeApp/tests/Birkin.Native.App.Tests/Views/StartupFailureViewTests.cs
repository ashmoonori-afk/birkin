using System.IO;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Media.Imaging;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Startup;
using Birkin.Native.App.Views;
using Birkin.Native.Shell.Lifecycle;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;
using StartupOwnedBridgeProcess =
    Birkin.Native.App.Startup.OwnedBridgeProcess;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
public sealed class StartupFailureViewTests
{
    [TestMethod]
    [DoNotParallelize]
    public async Task StartupFailure_WhenPathHasNoBirkin_RendersEnabledRetry()
    {
        // Given
        var previousPath = Environment.GetEnvironmentVariable("PATH");
        BridgeStartupResult result;
        try
        {
            Environment.SetEnvironmentVariable(
                "PATH",
                Path.Combine(Path.GetTempPath(), $"birkin-empty-{Guid.NewGuid():N}"));
            var supervisor = new BridgeSupervisor(
                () => TimeSpan.Zero,
                () => StartupOwnedBridgeProcess.Start(_ => { }, "birkin"));

            // When
            result = await BridgeStartup.StartOwnedAsync(
                supervisor,
                CancellationToken.None);
        }
        finally
        {
            Environment.SetEnvironmentVariable("PATH", previousPath);
        }

        // Then
        var startupFailure = result as BridgeStartupResult.Failed;
        Assert.IsNotNull(startupFailure);
        Assert.AreEqual(
            BridgeStartupFailureReason.CliUnavailable,
            startupFailure.Reason);

        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        _ = await sta.InvokeAsync(() =>
        {
            var model = new ShellPresentationModel(
                new ImmediateSynchronizationContext());
            model.PresentStartupFailure(
                StartupFailurePresentation.Create(startupFailure.Reason));
            var view = new WorkspaceSnapshotView(model);
            OfficeWorkflowViewHarness.Layout(view);

            Assert.IsTrue(
                OfficeWorkflowViewHarness.Find<Button>(
                    view,
                    "startup.failure.retry").IsEnabled);
            return true;
        });
    }

    [TestMethod]
    public async Task StartupFailure_WhenCliFails_RendersReasonAndRecovery()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(() =>
        {
            var model = new ShellPresentationModel(
                new ImmediateSynchronizationContext());
            var failure = StartupFailurePresentation.Create(
                BridgeStartupFailureReason.CliFailed);
            model.PresentStartupFailure(failure);
            var view = new WorkspaceSnapshotView(model);
            var recovery = new RecordingStartupRecovery();
            view.AttachStartupRecovery(model, recovery);

            // When
            OfficeWorkflowViewHarness.Layout(view);

            // Then
            Assert.IsNotNull(OfficeWorkflowViewHarness.Find<Border>(
                view,
                "startup.failure"));
            var title = OfficeWorkflowViewHarness.Find<TextBlock>(
                view,
                "startup.failure.title");
            Assert.AreEqual(
                failure.Title,
                title.Text);
            Assert.IsTrue(title.Focusable);
            Assert.AreEqual(
                failure.Title,
                AutomationProperties.GetName(title));
            Assert.AreEqual(
                AutomationLiveSetting.Assertive,
                AutomationProperties.GetLiveSetting(title));
            Assert.AreEqual(
                failure.Explanation,
                OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "startup.failure.explanation").Text);
            Assert.AreEqual(
                failure.RecoveryAction,
                OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "startup.failure.recovery").Text);
            Assert.AreEqual(
                "CONNECTION FAILED",
                OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "ConnectionStatusText").Text);
            Assert.AreSame(
                view.FindResource("MutedBrush"),
                OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "startup.failure.code").Foreground);
            WriteEvidence(view);

            var executablePath = OfficeWorkflowViewHarness.Find<TextBox>(
                view,
                "startup.failure.executable-path");
            Assert.AreEqual(string.Empty, executablePath.Text);
            executablePath.Text = @"C:\Tools\birkin.exe";
            var configure = OfficeWorkflowViewHarness.Find<Button>(
                view,
                "startup.failure.configure");
            Assert.AreEqual("경로 저장 후 다시 시도", configure.Content);
            Assert.AreEqual(
                "Birkin 실행 파일 경로를 저장하고 다시 시도",
                AutomationProperties.GetName(configure));

            // When
            configure.RaiseEvent(
                new System.Windows.RoutedEventArgs(Button.ClickEvent));
            view.Dispatcher.Invoke(
                () => { },
                System.Windows.Threading.DispatcherPriority.SystemIdle);

            // Then
            Assert.AreEqual(
                @"C:\Tools\birkin.exe",
                recovery.ConfiguredPathRequest);
            Assert.IsTrue(model.HasStartupFailure);

            var retry = OfficeWorkflowViewHarness.Find<Button>(
                view,
                "startup.failure.retry");
            Assert.IsTrue(retry.IsEnabled);
            Assert.AreEqual("다시 시도", retry.Content);
            Assert.AreEqual(
                "Birkin CLI 시작 다시 시도",
                AutomationProperties.GetName(retry));
            Assert.AreEqual(
                "Birkin 실행 파일 경로",
                AutomationProperties.GetName(executablePath));

            // When
            retry.RaiseEvent(new System.Windows.RoutedEventArgs(Button.ClickEvent));
            view.Dispatcher.Invoke(
                () => { },
                System.Windows.Threading.DispatcherPriority.SystemIdle);

            // Then
            Assert.AreEqual(1, recovery.RetryCalls);
            Assert.IsNull(model.StartupFailure);
            Assert.IsFalse(model.HasStartupFailure);
            return true;
        });
    }

    [TestMethod]
    public async Task StartupFailure_WhenBridgeCrashLoops_RendersSpecificReasonBanner()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);

        // When / Then
        await sta.InvokeAsync(() =>
        {
            var model = new ShellPresentationModel(
                new ImmediateSynchronizationContext());
            model.PresentStartupFailure(
                StartupFailurePresentation.Create(
                    BridgeStartupFailureReason.CliCrashLoop));
            var view = new WorkspaceSnapshotView(model);
            OfficeWorkflowViewHarness.Layout(view);

            Assert.AreEqual(
                "Birkin CLI가 반복해서 종료되었습니다",
                OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "startup.failure.title").Text);
            Assert.AreEqual(
                "birkin 명령이 1분 안에 5번 종료되었습니다.",
                OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "startup.failure.explanation").Text);
            Assert.AreEqual(
                "E_CLI_CRASH_LOOP",
                OfficeWorkflowViewHarness.Find<TextBlock>(
                    view,
                    "startup.failure.code").Text);
            Assert.IsTrue(
                OfficeWorkflowViewHarness.Find<Button>(
                    view,
                    "startup.failure.retry").IsEnabled);
            return true;
        });
    }

    private static void WriteEvidence(WorkspaceSnapshotView view)
    {
        const int width = 1100;
        const int height = 720;
        view.Measure(new System.Windows.Size(width, height));
        view.Arrange(new System.Windows.Rect(0, 0, width, height));
        view.UpdateLayout();
        var bitmap = new RenderTargetBitmap(
            width,
            height,
            96,
            96,
            System.Windows.Media.PixelFormats.Pbgra32);
        bitmap.Render(view);
        var encoder = new PngBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(bitmap));
        var path = EvidencePath();
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        using var stream = File.Create(path);
        encoder.Save(stream);
        Assert.IsTrue(stream.Length > 0);
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
            "windows-first-run-failure.png");
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

    private sealed class ImmediateSynchronizationContext :
        SynchronizationContext
    {
        public override void Post(
            SendOrPostCallback callback,
            object? state) => callback(state);
    }

    private sealed class RecordingStartupRecovery : IStartupRecovery
    {
        public string? ConfiguredPathRequest { get; private set; }

        public int RetryCalls { get; private set; }

        public Task<StartupFailurePresentation?> RetryAsync()
        {
            RetryCalls++;
            return Task.FromResult<StartupFailurePresentation?>(null);
        }

        public Task<StartupFailurePresentation?>
            ConfigureExecutableAndRetryAsync(string executablePath)
        {
            ConfiguredPathRequest = executablePath;
            return Task.FromResult<StartupFailurePresentation?>(
                StartupFailurePresentation.Create(
                    BridgeStartupFailureReason.CliFailed));
        }
    }
}
