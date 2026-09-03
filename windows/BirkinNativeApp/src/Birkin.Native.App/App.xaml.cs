using System.Windows;
using System.Windows.Threading;
using Birkin.Native.App.Startup;
using Birkin.Native.Shell.Lifecycle;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App;

public partial class App : Application
{
    private const string AnnouncementFileEnvironmentVariable = "BIRKIN_BRIDGE_ANNOUNCEMENT_FILE";
    private readonly CancellationTokenSource _shutdown = new();
    private CompositionRoot? _composition;
    private WindowsApprovalToast? _approvalToast;
    private bool _showApprovalsWhenReady;

    protected override async void OnStartup(StartupEventArgs eventArgs)
    {
        base.OnStartup(eventArgs);
        var context = SynchronizationContext.Current
            ?? new DispatcherSynchronizationContext(Dispatcher);
        var composition = CompositionRoot.Create(context);
        _composition = composition;
        _approvalToast = WindowsApprovalToast.Create(ShowApprovals);
        MainWindow = _approvalToast is null
            ? new MainWindow(
                composition.PresentationModel,
                composition.Coordinator,
                composition.Runner)
            : new MainWindow(
                composition.PresentationModel,
                composition.Coordinator,
                composition.Runner,
                _approvalToast);
        if (_showApprovalsWhenReady)
        {
            ShowApprovals();
        }
        MainWindow.Show();
        try
        {
            var options = AppOptions.Parse(StartupArguments(eventArgs.Args));
            var failure = await composition.Runner.RunAsync(
                options,
                _shutdown.Token);
            if (failure is not null)
            {
                composition.PresentationModel.PresentStartupFailure(failure);
            }
        }
        catch (ArgumentException)
        {
            composition.PresentationModel.PresentStartupFailure(
                StartupFailurePresentation.Create(
                    BridgeStartupFailureReason.CliFailed,
                    canRetry: false));
        }
        catch (OperationCanceledException) when (_shutdown.IsCancellationRequested)
        {
            // App shutdown owns this cancellation.
        }
    }

    protected override void OnExit(ExitEventArgs eventArgs)
    {
        _shutdown.Cancel();
        _approvalToast?.Dispose();
        if (_composition is not null)
        {
            _composition.DisposeAsync().AsTask().GetAwaiter().GetResult();
        }
        _shutdown.Dispose();
        base.OnExit(eventArgs);
    }

    private void ShowApprovals()
    {
        _ = Dispatcher.BeginInvoke(() =>
        {
            if (MainWindow is Birkin.Native.App.MainWindow window)
            {
                _showApprovalsWhenReady = false;
                window.ShowApprovals();
            }
            else
            {
                _showApprovalsWhenReady = true;
            }
        });
    }

    private static IReadOnlyList<string> StartupArguments(IReadOnlyList<string> arguments)
    {
        if (arguments.Count != 0)
        {
            return arguments;
        }
        var announcementFile = Environment.GetEnvironmentVariable(AnnouncementFileEnvironmentVariable);
        return announcementFile is null
            ? arguments
            : ["--bridge-announcement-file", announcementFile];
    }
}
