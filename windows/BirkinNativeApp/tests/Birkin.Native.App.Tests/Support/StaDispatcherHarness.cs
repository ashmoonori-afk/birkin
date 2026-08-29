using System.Windows.Threading;

namespace Birkin.Native.App.Tests.Support;

internal sealed class StaDispatcherHarness : IAsyncDisposable
{
    private readonly Dispatcher _dispatcher;
    private readonly Thread _thread;

    private StaDispatcherHarness(Dispatcher dispatcher, Thread thread)
    {
        _dispatcher = dispatcher;
        _thread = thread;
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
        return new StaDispatcherHarness(dispatcher, thread);
    }

    public Task<T> InvokeAsync<T>(Func<T> action) => _dispatcher.InvokeAsync(action).Task;

    public Task InvokeAsync(Func<Task> action) =>
        _dispatcher.InvokeAsync(action).Task.Unwrap();

    public async ValueTask DisposeAsync()
    {
        await _dispatcher.InvokeAsync(_dispatcher.InvokeShutdown).Task;
        _thread.Join();
    }
}
