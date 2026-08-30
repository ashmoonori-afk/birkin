using System.Windows.Threading;

namespace Birkin.Native.App.Tests.Support;

internal sealed class StaDispatcherHarness : IAsyncDisposable
{
    private readonly Dispatcher _dispatcher;
    private readonly CancellationToken _deadline;
    private readonly Thread _thread;

    private StaDispatcherHarness(
        Dispatcher dispatcher,
        Thread thread,
        CancellationToken deadline)
    {
        _dispatcher = dispatcher;
        _thread = thread;
        _deadline = deadline;
    }

    public static async Task<StaDispatcherHarness> StartAsync(CancellationToken cancellationToken)
    {
        var started = new TaskCompletionSource<Dispatcher>(TaskCreationOptions.RunContinuationsAsynchronously);
        var thread = new Thread(() =>
        {
            var dispatcher = Dispatcher.CurrentDispatcher;
            SynchronizationContext.SetSynchronizationContext(new DispatcherSynchronizationContext(dispatcher));
            started.TrySetResult(dispatcher);
            Dispatcher.Run();
        })
        {
            IsBackground = true,
            Name = "Birkin WPF control test dispatcher",
        };
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        var dispatcher = await started.Task.WaitAsync(cancellationToken);
        return new StaDispatcherHarness(dispatcher, thread, cancellationToken);
    }

    public Task<T> InvokeAsync<T>(Func<T> action) =>
        _dispatcher.InvokeAsync(action).Task.WaitAsync(_deadline);

    public Task InvokeAsync(Func<Task> action) =>
        _dispatcher.InvokeAsync(action).Task.Unwrap().WaitAsync(_deadline);

    public ValueTask DisposeAsync()
    {
        if (!_dispatcher.HasShutdownStarted)
        {
            _dispatcher.BeginInvokeShutdown(DispatcherPriority.Send);
        }
        if (!_thread.Join(TimeSpan.FromSeconds(5)))
        {
            throw new TimeoutException(
                "The WPF test dispatcher did not stop within five seconds.");
        }
        return ValueTask.CompletedTask;
    }
}
