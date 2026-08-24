using System.Windows;
using System.Windows.Threading;
using Birkin.Native.App.Startup;

namespace Birkin.Native.App;

public partial class App : Application
{
    private const string AnnouncementFileEnvironmentVariable = "BIRKIN_BRIDGE_ANNOUNCEMENT_FILE";
    private readonly CancellationTokenSource _shutdown = new();
    private CompositionRoot? _composition;

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
            MainWindow = new MainWindow(_composition.PresentationModel);
            if (eventArgs.Args.Length == 0)
            {
                await _composition.Runner.RunAsync(options, _shutdown.Token);
                MainWindow.Show();
            }
            else
            {
                MainWindow.Show();
                await _composition.Runner.RunAsync(options, _shutdown.Token);
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
    }

    protected override void OnExit(ExitEventArgs eventArgs)
    {
        _shutdown.Cancel();
        if (_composition is not null)
        {
            _composition.DisposeAsync().AsTask().GetAwaiter().GetResult();
        }
        _shutdown.Dispose();
        base.OnExit(eventArgs);
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
