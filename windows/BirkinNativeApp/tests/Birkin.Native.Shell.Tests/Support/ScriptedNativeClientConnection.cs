using System.Threading.Channels;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Transport;

namespace Birkin.Native.Shell.Tests.Support;

internal sealed class ScriptedNativeClientConnection : INativeClientConnection
{
    private readonly Channel<ReceiveStep> _steps = Channel.CreateUnbounded<ReceiveStep>(
        new UnboundedChannelOptions { SingleReader = true, AllowSynchronousContinuations = false });
    private readonly object _concurrencyGate = new();
    private int _activeReceives;
    private int _maxConcurrentReceives;

    public TaskCompletionSource Reconnected { get; } =
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    public TaskCompletionSource ReceiveCancelled { get; } =
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    public int ActiveReceives => Volatile.Read(ref _activeReceives);

    public int DisposeCalls { get; private set; }

    public int Reconnects { get; private set; }

    public int MaxConcurrentReceives
    {
        get
        {
            lock (_concurrencyGate)
            {
                return _maxConcurrentReceives;
            }
        }
    }

    public void Enqueue(NativeEnvelope envelope) => Write(new ReceiveStep.Frame(envelope));

    public void EnqueueReconnect() => Write(new ReceiveStep.Reconnect());

    public Task ConnectAsync(
        BridgeAnnouncement announcement,
        string expectedProductVersion,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return Task.CompletedTask;
    }

    public async ValueTask<NativeEnvelope> ReceiveAsync(CancellationToken cancellationToken)
    {
        var active = Interlocked.Increment(ref _activeReceives);
        lock (_concurrencyGate)
        {
            _maxConcurrentReceives = Math.Max(_maxConcurrentReceives, active);
        }
        try
        {
            while (true)
            {
                var step = await _steps.Reader.ReadAsync(cancellationToken).ConfigureAwait(false);
                switch (step)
                {
                    case ReceiveStep.Frame frame:
                        return frame.Envelope;
                    case ReceiveStep.Reconnect:
                        Reconnects++;
                        Reconnected.TrySetResult();
                        break;
                    default:
                        throw new InvalidOperationException("unsupported scripted receive step");
                }
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            ReceiveCancelled.TrySetResult();
            throw;
        }
        finally
        {
            _ = Interlocked.Decrement(ref _activeReceives);
        }
    }

    public ValueTask DisposeAsync()
    {
        DisposeCalls++;
        _steps.Writer.TryComplete();
        return ValueTask.CompletedTask;
    }

    private void Write(ReceiveStep step)
    {
        if (!_steps.Writer.TryWrite(step))
        {
            throw new InvalidOperationException("scripted connection is closed");
        }
    }

    private abstract record ReceiveStep
    {
        public sealed record Frame(NativeEnvelope Envelope) : ReceiveStep;

        public sealed record Reconnect : ReceiveStep;
    }
}
