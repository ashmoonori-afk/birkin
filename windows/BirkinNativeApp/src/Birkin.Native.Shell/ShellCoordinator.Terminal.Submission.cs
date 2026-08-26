using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.Shell;

public sealed partial class ShellCoordinator
{
    private Task<bool> SubmitTerminalControlAsync(
        string terminalId,
        string commandType,
        Func<TerminalLeaseControl, CommandRequestContext, NativeCommandRequest> requestFactory,
        bool incrementsSequence,
        CancellationToken cancellationToken) =>
        SubmitTerminalAsync(
            commandType,
            context =>
            {
                if (!_terminalControls.TryGetValue(terminalId, out var control))
                {
                    throw new NativeProtocolError("E_STATE", "terminal mutation authority is unavailable");
                }
                return requestFactory(control, context);
            },
            terminalId,
            incrementsSequence,
            cancellationToken);

    private async Task<bool> SubmitTerminalAsync(
        string commandType,
        Func<CommandRequestContext, NativeCommandRequest> requestFactory,
        string? terminalId,
        bool incrementsSequence,
        CancellationToken cancellationToken)
    {
        var commandId = CommandIdFactory();
        var authority = CaptureConnectionAuthority();
        NativeCommandRequest? request = null;
        bool drain;
        lock (_stateLock)
        {
            var availability = TerminalAvailabilityLocked(commandType, terminalId, authority);
            if (!availability.IsEnabled || _workflow.HasPendingCommand || _terminalWorkflow.HasPendingCommand)
            {
                if (!authority.IsLive)
                {
                    ClearWorkflowAuthorityLocked();
                    ClearTerminalAuthorityLocked();
                }
                RefreshMutationAvailabilityLocked(authority);
                drain = EnqueuePresentationLocked(new(null, null, _workflow, _terminalWorkflow));
            }
            else
            {
                var context = new CommandRequestContext(
                    commandId,
                    _terminalWorkflow.CurrentCursor ?? _projectionState?.Cursor ?? 0,
                    NativeHandshake.ViewId);
                request = requestFactory(context);
                _terminalWorkflow = _terminalWorkflow.Begin(commandId, commandType);
                RefreshMutationAvailabilityLocked(authority);
                drain = EnqueuePresentationLocked(new(null, null, _workflow, _terminalWorkflow));
            }
        }
        DrainPresentations(drain);

        if (request is null)
        {
            return false;
        }

        try
        {
            var receipt = await SendTerminalForResultAsync(request, cancellationToken).ConfigureAwait(false);
            AcceptTerminalReceipt(receipt, request.CommandId, commandType, terminalId, incrementsSequence);
            return true;
        }
        catch (NativeCommandRefusal refusal)
        {
            RefuseTerminal(refusal);
            return false;
        }
        catch (NativeProtocolError)
        {
            var currentAuthority = CaptureConnectionAuthority();
            if (currentAuthority.IsLive)
            {
                throw;
            }
            ClearWorkflowAuthority();
            return false;
        }
    }

    private async Task<NativeEnvelope> SendTerminalForResultAsync(
        NativeCommandRequest request,
        CancellationToken cancellationToken)
    {
        if (_connection.OwnsReceiveLoop)
        {
            return await _connection.SendCommandForResultAsync(request, cancellationToken).ConfigureAwait(false);
        }

        await _connection.SendCommandAsync(request, cancellationToken).ConfigureAwait(false);
        for (var received = 0; received < MaxFramesBeforeCommandResult; received++)
        {
            var envelope = await _connection.ReceiveAsync(cancellationToken).ConfigureAwait(false);
            if (envelope.Kind == NativeMessageKind.Receipt)
            {
                return envelope;
            }
            ApplyCanonicalFrame(envelope);
            if (envelope.Kind == NativeMessageKind.Goodbye
                || envelope.Kind == NativeMessageKind.Error)
            {
                throw new NativeProtocolError("E_STATE", "terminal command ended before its receipt");
            }
        }
        throw new NativeProtocolError("E_FLOW_VIOLATION", "terminal command result exceeded frame bound");
    }
}
