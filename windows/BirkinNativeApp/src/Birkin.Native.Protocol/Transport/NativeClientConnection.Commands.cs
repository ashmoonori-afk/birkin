using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Protocol.Transport;

public sealed partial class NativeClientConnection
{
    private readonly object _commandGate = new();
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
            if (!string.Equals(envelope.InReplyTo, _pendingCommandFrameId, StringComparison.Ordinal)
                || _pendingCommandId is null)
            {
                throw CorrelationError();
            }

            commandId = _pendingCommandId;
            if (envelope.Kind == NativeMessageKind.Receipt
                && (!TryString(envelope.Body, "command_id", out var receivedCommandId)
                    || !string.Equals(receivedCommandId, commandId, StringComparison.Ordinal)))
            {
                throw CorrelationError();
            }

            _pendingCommandFrameId = null;
            _pendingCommandId = null;
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

        if (!TryString(body, "message", out var message))
        {
            throw new NativeProtocolError("E_BODY", "command refusal message is invalid");
        }

        long? currentCursor = body["current_cursor"] is NativeJsonInteger cursor
            ? cursor.Value
            : null;
        if (string.Equals(code, "E_STALE_CURSOR", StringComparison.Ordinal)
            && currentCursor is null)
        {
            throw new NativeProtocolError("E_BODY", "stale cursor refusal lacks current_cursor");
        }

        var approvalId = string.Equals(code, "E_TERMINAL_APPROVAL_REQUIRED", StringComparison.Ordinal)
            && TryString(body, "approval_id", out var receivedApprovalId)
                ? receivedApprovalId
                : null;

        return new NativeCommandRefusal(code, message, commandId, currentCursor, approvalId);
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
