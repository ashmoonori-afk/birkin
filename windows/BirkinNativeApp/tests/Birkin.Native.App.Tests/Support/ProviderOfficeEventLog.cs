using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Support;

internal sealed class ProviderOfficeEventLog : IDisposable
{
    private readonly NativeProjectionStore _store;
    private readonly object _gate = new();
    private readonly List<NativeEnvelope> _events = [];
    private readonly List<Waiter> _waiters = [];

    public ProviderOfficeEventLog(NativeProjectionStore store)
    {
        _store = store;
        store.CanonicalApplied += Applied;
    }

    public IReadOnlyList<NativeEnvelope> Events
    {
        get
        {
            lock (_gate)
            {
                return _events.ToArray();
            }
        }
    }

    public Task<NativeEnvelope> WaitAsync(
        string type,
        string commandId,
        CancellationToken cancellationToken) => WaitAsync(
            envelope => Type(envelope) == type && CommandId(envelope) == commandId,
            cancellationToken);

    public Task<NativeEnvelope> WaitAsync(
        Func<NativeEnvelope, bool> predicate,
        CancellationToken cancellationToken)
    {
        lock (_gate)
        {
            var existing = _events.FirstOrDefault(predicate);
            if (existing is not null)
            {
                return Task.FromResult(existing);
            }

            var completion = new TaskCompletionSource<NativeEnvelope>(TaskCreationOptions.RunContinuationsAsynchronously);
            var waiter = new Waiter(predicate, completion);
            _waiters.Add(waiter);
            cancellationToken.Register(() =>
            {
                lock (_gate)
                {
                    _ = _waiters.Remove(waiter);
                }
                completion.TrySetCanceled(cancellationToken);
            });
            return completion.Task;
        }
    }

    public void Dispose() => _store.CanonicalApplied -= Applied;

    public static string Type(NativeEnvelope envelope) => String(envelope.Body, "type");

    public static string CommandId(NativeEnvelope envelope) => String(envelope.Body, "command_id");

    public static long Cursor(NativeEnvelope envelope) => Integer(envelope.Body, "cursor");

    public static string EventId(NativeEnvelope envelope) => String(envelope.Body, "event_id");

    public static NativeJsonObject Payload(NativeEnvelope envelope) => Object(envelope.Body, "payload");

    public static NativeJsonObject Object(NativeJsonObject value, string key) =>
        value[key] as NativeJsonObject ?? throw new AssertFailedException($"{key} is not an object");

    public static NativeJsonArray Array(NativeJsonObject value, string key) =>
        value[key] as NativeJsonArray ?? throw new AssertFailedException($"{key} is not an array");

    public static string String(NativeJsonObject value, string key) =>
        value[key] is NativeJsonString text
            ? text.Value
            : throw new AssertFailedException($"{key} is not a string");

    public static long Integer(NativeJsonObject value, string key) =>
        value[key] is NativeJsonInteger integer
            ? integer.Value
            : throw new AssertFailedException($"{key} is not an integer");

    public static bool Boolean(NativeJsonObject value, string key) =>
        value[key] is NativeJsonBoolean flag
            ? flag.Value
            : throw new AssertFailedException($"{key} is not a boolean");

    private void Applied(NativeEnvelope envelope)
    {
        if (envelope.Kind != NativeMessageKind.Event)
        {
            return;
        }

        List<Waiter> matched;
        lock (_gate)
        {
            _events.Add(envelope);
            matched = _waiters.Where(waiter => waiter.Predicate(envelope)).ToList();
            foreach (var waiter in matched)
            {
                _ = _waiters.Remove(waiter);
            }
        }
        foreach (var waiter in matched)
        {
            waiter.Completion.TrySetResult(envelope);
        }
    }

    private sealed record Waiter(
        Func<NativeEnvelope, bool> Predicate,
        TaskCompletionSource<NativeEnvelope> Completion);
}
