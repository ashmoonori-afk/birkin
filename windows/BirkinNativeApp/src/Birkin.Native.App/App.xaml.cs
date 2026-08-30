using System.Windows;
using System.Windows.Threading;
using Birkin.Native.App.Startup;

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
        try
        {
            var arguments = StartupArguments(eventArgs.Args);
            var options = AppOptions.Parse(arguments);
            var context = SynchronizationContext.Current
                ?? new DispatcherSynchronizationContext(Dispatcher);
            _composition = CompositionRoot.Create(context);
            _approvalToast = WindowsApprovalToast.Create(ShowApprovals);
            MainWindow = _approvalToast is null
                ? new MainWindow(
                    _composition.PresentationModel,
                    _composition.Coordinator,
                    _composition.Runner)
                : new MainWindow(
                    _composition.PresentationModel,
                    _composition.Coordinator,
                    _composition.Runner,
                    _approvalToast);
            if (_showApprovalsWhenReady)
            {
                ShowApprovals();
            }
            MainWindow.Show();
            var failure = await _composition.Runner.RunAsync(
                options,
                _shutdown.Token);
            if (failure is not null)
            {
                _composition.PresentationModel.PresentStartupFailure(failure);
            }
        }
        catch (ArgumentException error)
        {
            MessageBox.Show(
                error.Message,
                "Birkin for Windows - Development Preview",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            Shutdown(2);
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
