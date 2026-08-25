using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Protocol.Transport;

public sealed partial class NativeClientConnection
{
    private const int MaxAbandonedCommands = 128;
    private readonly object _commandGate = new();
    private readonly Dictionary<string, string> _abandonedCommandFrames = new(StringComparer.Ordinal);
    private readonly Queue<string> _abandonedCommandFrameOrder = new();
    private string? _pendingCommandFrameId;
    private string? _pendingCommandId;

    public async ValueTask SendCommandAsync(
        NativeCommandRequest request,
        CancellationToken cancellationToken)
    {
        var transport = _transport
            ?? throw new NativeProtocolError("E_STATE", "connection is not active");
        if (!_subscribed)
        {
            throw new NativeProtocolError("E_STATE", "connection is not subscribed");
        }

        var capability = CurrentCapability
            ?? throw new NativeProtocolError("E_CAPABILITY_EXPIRED", "session capability is unavailable");
        var envelope = request.CreateEnvelope(NextId(), capability);
        lock (_commandGate)
        {
            if (_pendingCommandFrameId is not null)
            {
                throw new NativeProtocolError("E_FLOW_VIOLATION", "connection already has a pending command");
            }

            _pendingCommandFrameId = envelope.Id;
            _pendingCommandId = request.CommandId;
        }

        var sent = false;
        try
        {
            Claim(envelope.Id);
            await transport.SendAsync(envelope, cancellationToken).ConfigureAwait(false);
            sent = true;
        }
        finally
        {
            if (!sent)
            {
                ClearPendingCommand(envelope.Id);
            }
        }
    }

    private void ValidateCommandCorrelation(NativeEnvelope envelope)
    {
        if (envelope.InReplyTo is null)
        {
            if (envelope.Kind == NativeMessageKind.Receipt)
            {
                throw CorrelationError();
            }

            return;
        }

        if (envelope.Kind != NativeMessageKind.Receipt
            && envelope.Kind != NativeMessageKind.Error)
        {
            throw CorrelationError();
        }

        string commandId;
        lock (_commandGate)
        {
            if (string.Equals(envelope.InReplyTo, _pendingCommandFrameId, StringComparison.Ordinal)
                && _pendingCommandId is { } pendingCommandId)
            {
                commandId = pendingCommandId;
                _pendingCommandFrameId = null;
                _pendingCommandId = null;
            }
            else if (_abandonedCommandFrames.Remove(envelope.InReplyTo, out var abandonedCommandId))
            {
                commandId = abandonedCommandId;
            }
            else
            {
                throw CorrelationError();
            }

            if (envelope.Kind == NativeMessageKind.Receipt
                && (!TryString(envelope.Body, "command_id", out var receivedCommandId)
                    || !string.Equals(receivedCommandId, commandId, StringComparison.Ordinal)))
            {
                throw CorrelationError();
            }
        }

        if (envelope.Kind == NativeMessageKind.Error)
        {
            var refusal = CreateRefusal(envelope.Body, commandId);
            if (string.Equals(refusal.Code, "E_CAPABILITY_EXPIRED", StringComparison.Ordinal))
            {
                ClearAuthority();
            }

            throw refusal;
        }
    }

    internal void AbandonPendingCommand(string commandId)
    {
        lock (_commandGate)
        {
            if (!string.Equals(commandId, _pendingCommandId, StringComparison.Ordinal)
                || _pendingCommandFrameId is not { } frameId)
            {
                return;
            }

            _abandonedCommandFrames[frameId] = commandId;
            _abandonedCommandFrameOrder.Enqueue(frameId);
            while (_abandonedCommandFrameOrder.Count > MaxAbandonedCommands)
            {
                _abandonedCommandFrames.Remove(_abandonedCommandFrameOrder.Dequeue());
            }
            _pendingCommandFrameId = null;
            _pendingCommandId = null;
        }
    }

    internal async ValueTask SendGoodbyeAsync(CancellationToken cancellationToken)
    {
        var transport = _transport
            ?? throw new NativeProtocolError("E_STATE", "connection is not active");
        var capability = CurrentCapability
            ?? throw new NativeProtocolError("E_CAPABILITY_EXPIRED", "session capability is unavailable");
        var goodbye = new NativeEnvelope(
            NativeMessageKind.Goodbye,
            NextId(),
            new NativeJsonObject([
                new("session_capability", new NativeJsonString(capability.Token)),
                new("reason", new NativeJsonString("app_shutdown")),
            ]));
        NativeBodyValidator.Validate(goodbye, NativeMessageOrigin.Client);
        Claim(goodbye.Id);
        await transport.SendAsync(goodbye, cancellationToken).ConfigureAwait(false);
    }

    private void ClearPendingCommand(string? expectedFrameId = null)
    {
        lock (_commandGate)
        {
            if (expectedFrameId is not null
                && !string.Equals(expectedFrameId, _pendingCommandFrameId, StringComparison.Ordinal))
            {
                return;
            }

            _pendingCommandFrameId = null;
            _pendingCommandId = null;
            _abandonedCommandFrames.Clear();
            _abandonedCommandFrameOrder.Clear();
        }
    }

    private string NextId() => $"client-{Interlocked.Increment(ref _nextId)}";

    private void Claim(string id)
    {
        lock (_idGate)
        {
            if (!_seenIds.Add(id))
            {
                throw new NativeProtocolError(
                    "E_DUPLICATE_FRAME_ID",
                    "frame id was reused inside the connection replay window");
            }

            _idOrder.Enqueue(id);
            if (_idOrder.Count > MaxTrackedFrameIds)
            {
                _seenIds.Remove(_idOrder.Dequeue());
            }
        }
    }

    private static NativeCommandRefusal CreateRefusal(NativeJsonObject body, string commandId)
    {
        if (!TryString(body, "code", out var code))
        {
            throw new NativeProtocolError("E_BODY", "command refusal code is invalid");
        }

        long? currentCursor = body["current_cursor"] is NativeJsonInteger cursor
            ? cursor.Value
            : null;
        if (string.Equals(code, "E_STALE_CURSOR", StringComparison.Ordinal)
            && currentCursor is null)
        {
            throw new NativeProtocolError("E_BODY", "stale cursor refusal lacks current_cursor");
        }

        return new NativeCommandRefusal(code, commandId, currentCursor);
    }

    private static bool TryString(NativeJsonObject body, string key, out string value)
    {
        if (body[key] is NativeJsonString text)
        {
            value = text.Value;
            return true;
        }

        value = string.Empty;
        return false;
    }

    private static NativeProtocolError CorrelationError() =>
        new("E_CORRELATION", "server response does not match the pending command");
}
