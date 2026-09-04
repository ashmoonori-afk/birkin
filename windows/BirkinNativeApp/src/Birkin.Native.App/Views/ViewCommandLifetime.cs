namespace Birkin.Native.App.Views;

internal sealed class ViewCommandLifetime : IDisposable
{
    private readonly CancellationTokenSource _source = new();
    private readonly CancellationToken _token;

    public ViewCommandLifetime() => _token = _source.Token;

    public async Task RunAsync(Func<CancellationToken, Task> command)
    {
        try
        {
            await command(_token);
        }
        catch (OperationCanceledException) when (_token.IsCancellationRequested)
        {
        }
    }

    public void Dispose()
    {
        _source.Cancel();
        _source.Dispose();
    }
}
