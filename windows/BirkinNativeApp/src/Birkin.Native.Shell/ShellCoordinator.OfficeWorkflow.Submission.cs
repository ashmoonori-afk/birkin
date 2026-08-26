using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.Shell;

public sealed partial class ShellCoordinator
{
    private async Task<bool> SubmitAsync(
        Func<string, CommandRequestContext, NativeCommandRequest> requestFactory,
        bool conversationProjectionRequired,
        CancellationToken cancellationToken)
    {
        var commandId = CommandIdFactory();
        var authority = CaptureConnectionAuthority();
        NativeCommandRequest? request = null;
        bool drain;
        lock (_stateLock)
        {
            if (conversationProjectionRequired && string.IsNullOrWhiteSpace(_workflow.Draft))
            {
                return false;
            }

            var context = new CommandRequestContext(
                commandId,
                _projectionState?.Cursor ?? 0,
                NativeHandshake.ViewId);
            request = requestFactory(_workflow.Draft, context);
            var projectionPermits = !conversationProjectionRequired || ProjectionPermitsConversationLocked();
            var availability = AvailabilityLocked(request.CommandType, projectionPermits, authority);
            if (!availability.IsEnabled || _workflow.HasPendingCommand || _terminalWorkflow.HasPendingCommand)
            {
                if (!authority.IsLive)
                {
                    ClearWorkflowAuthorityLocked();
                    ClearTerminalAuthorityLocked();
                }
                else
                {
                    RefreshMutationAvailabilityLocked(authority);
                }
                drain = EnqueuePresentationLocked(new(null, null, _workflow, _terminalWorkflow));
                request = null;
            }
            else
            {
                _workflow = _workflow.Begin(request.CommandId, request.CommandType);
                _pendingDraftRevision = conversationProjectionRequired ? _draftRevision : null;
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
            if (_connection.OwnsReceiveLoop)
            {
                var receipt = await _connection.SendCommandForResultAsync(request, cancellationToken).ConfigureAwait(false);
                AcceptReceipt(receipt, request.CommandId);
                return true;
            }

            await _connection.SendCommandAsync(request, cancellationToken).ConfigureAwait(false);
            return await ReceiveCommandResultAsync(request.CommandId, cancellationToken).ConfigureAwait(false);
        }
        catch (NativeCommandRefusal refusal)
        {
            Refuse(refusal);
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

    private async Task<bool> ReceiveCommandResultAsync(
        string commandId,
        CancellationToken cancellationToken)
    {
        for (var received = 0; received < MaxFramesBeforeCommandResult; received++)
        {
            var envelope = await _connection.ReceiveAsync(cancellationToken).ConfigureAwait(false);
            if (envelope.Kind == NativeMessageKind.Receipt)
            {
                AcceptReceipt(envelope, commandId);
                return true;
            }

            ApplyCanonicalFrame(envelope);
            if (envelope.Kind == NativeMessageKind.Goodbye
                || envelope.Kind == NativeMessageKind.Error)
            {
                return false;
            }
        }

        throw new NativeProtocolError("E_FLOW_VIOLATION", "command result exceeded frame bound");
    }

}
