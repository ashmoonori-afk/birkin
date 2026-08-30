using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.Shell;

public sealed partial class ShellCoordinator
{
    private const int MaxFramesBeforeCommandResult = 128;
    private OfficeWorkflowPresentation _workflow = OfficeWorkflowPresentation.Empty;
    private long _draftRevision;
    private long? _pendingDraftRevision;

    public void SetConversationDraft(string draft)
    {
        bool drain;
        lock (_stateLock)
        {
            _draftRevision++;
            _workflow = _workflow.WithDraft(draft);
            drain = EnqueuePresentationLocked(new(null, null, _workflow));
        }
        DrainPresentations(drain);
    }

    public Task<bool> SendConversationAsync(CancellationToken cancellationToken) =>
        SubmitAsync(
            (draft, context) => ConversationCommands.Send(draft, context),
            conversationProjectionRequired: true,
            cancellationToken);

    public Task<bool> ImportAsync(FileImportIntent intent, CancellationToken cancellationToken) =>
        SubmitAsync((_, context) => ImportCommands.Import(intent, context), false, cancellationToken);

    public Task<bool> AnswerApprovalAsync(
        ApprovalAnswerIntent intent,
        CancellationToken cancellationToken) =>
        SubmitAsync((_, context) => ApprovalCommands.Answer(intent, context), false, cancellationToken);

    public Task<bool> RequestOfficeRollbackAsync(
        OfficeRollbackRequestIntent intent,
        CancellationToken cancellationToken) =>
        SubmitAsync(
            (_, context) => OfficeCommands.RollbackRequest(intent, context),
            false,
            cancellationToken);

    public Task<bool> CreateOfficeDocumentAsync(
        OfficeCreateIntent intent,
        CancellationToken cancellationToken) => UnavailableOfficeMutation(cancellationToken);

    public Task<bool> SelectOfficeDocumentAsync(
        OfficeSelectIntent intent,
        CancellationToken cancellationToken) =>
        SubmitAsync((_, context) => OfficeCommands.Select(intent, context), false, cancellationToken);

    public Task<bool> OpenOfficeDocumentAsync(
        OfficeOpenIntent intent,
        CancellationToken cancellationToken) =>
        SubmitAsync((_, context) => OfficeCommands.Open(intent, context), false, cancellationToken);

    public Task<bool> CompareOfficeDocumentsAsync(
        OfficeCompareIntent intent,
        CancellationToken cancellationToken) =>
        SubmitAsync((_, context) => OfficeCommands.Compare(intent, context), false, cancellationToken);

    public Task<bool> DraftOfficeDocumentAsync(
        OfficeDraftIntent intent,
        CancellationToken cancellationToken) => UnavailableOfficeMutation(cancellationToken);

    public Task<bool> ConvertOfficeDocumentAsync(
        OfficeConvertIntent intent,
        CancellationToken cancellationToken) => UnavailableOfficeMutation(cancellationToken);

    private static Task<bool> UnavailableOfficeMutation(CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return Task.FromResult(false);
    }

    public async Task ReceiveCanonicalAsync(CancellationToken cancellationToken)
    {
        if (_connection.OwnsReceiveLoop)
        {
            cancellationToken.ThrowIfCancellationRequested();
            return;
        }

        var envelope = await _connection.ReceiveAsync(cancellationToken).ConfigureAwait(false);
        ApplyCanonicalFrame(envelope);
    }

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
            if (!availability.IsEnabled || _workflow.HasPendingCommand)
            {
                if (!authority.IsLive)
                {
                    ClearWorkflowAuthorityLocked();
                }
                else
                {
                    RefreshMutationAvailabilityLocked(authority);
                }
                drain = EnqueuePresentationLocked(new(null, null, _workflow));
                request = null;
            }
            else
            {
                _workflow = _workflow.Begin(request.CommandId, request.CommandType);
                _pendingDraftRevision = conversationProjectionRequired ? _draftRevision : null;
                RefreshMutationAvailabilityLocked(authority);
                drain = EnqueuePresentationLocked(new(null, null, _workflow));
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

    private void ApplyCanonicalFrame(NativeEnvelope envelope)
    {
        switch (envelope.Kind.WireName)
        {
            case "event":
                _projectionStore.ApplyEvent(envelope);
                break;
            case "surface_snapshot":
            case "surface_event":
                _projectionStore.ApplySurface(envelope);
                break;
            case "snapshot":
                ApplyCanonicalSnapshot(envelope);
                break;
            case "ping":
            case "pong":
            case "capability.renewed":
                RefreshMutationAvailability();
                break;
            case "goodbye":
            case "error":
                ClearWorkflowAuthority();
                break;
            default:
                throw new NativeProtocolError("E_STATE", "frame is not a canonical workflow update");
        }
    }

    private void AcceptReceipt(NativeEnvelope receipt, string commandId)
    {
        var receivedCommandId = String(receipt.Body, "command_id");
        if (!string.Equals(receivedCommandId, commandId, StringComparison.Ordinal))
        {
            throw new NativeProtocolError("E_CORRELATION", "receipt command does not match submitted intent");
        }

        var acceptedCursor = Integer(receipt.Body, "accepted_cursor");
        var authority = CaptureConnectionAuthority();
        bool drain;
        lock (_stateLock)
        {
            var draft = _workflow.Draft;
            var preserveDraft = _pendingDraftRevision is { } submittedRevision
                && submittedRevision != _draftRevision;
            _workflow = _workflow.Accept(commandId, acceptedCursor);
            if (preserveDraft)
            {
                _workflow = _workflow.WithDraft(draft);
            }
            RefreshMutationAvailabilityLocked(authority);
            drain = EnqueuePresentationLocked(new(null, null, _workflow));
        }
        DrainPresentations(drain);
    }

    private void Refuse(NativeCommandRefusal refusal)
    {
        var authority = CaptureConnectionAuthority();
        bool drain;
        lock (_stateLock)
        {
            _workflow = _workflow.Refuse(
                refusal.CommandId,
                refusal.Code,
                refusal.Message,
                refusal.Retryable,
                refusal.CurrentCursor);
            if (string.Equals(_workflow.CommandId, refusal.CommandId, StringComparison.Ordinal))
            {
                _pendingDraftRevision = null;
            }
            RefreshMutationAvailabilityLocked(authority);
            drain = EnqueuePresentationLocked(new(null, null, _workflow));
        }
        DrainPresentations(drain);
    }

    private void ResolveFromCanonicalEventLocked(NativeEnvelope envelope)
    {
        if (envelope.Body["command_id"] is not NativeJsonString commandId)
        {
            return;
        }

        var draft = _workflow.Draft;
        var preserveDraft = _pendingDraftRevision is { } submittedRevision
            && submittedRevision != _draftRevision;
        var resolved = _workflow.ResolveFromProjection(commandId.Value);
        if (!ReferenceEquals(resolved, _workflow))
        {
            _workflow = preserveDraft ? resolved.WithDraft(draft) : resolved;
            _pendingDraftRevision = null;
        }
    }

    private void ApplyCanonicalSnapshot(NativeEnvelope envelope)
    {
        NativeProjectionState current;
        lock (_stateLock)
        {
            current = _projectionState
                ?? throw new NativeProtocolError("E_STATE", "replacement snapshot requires canonical identity");
        }
        _projectionStore.ApplySnapshot(
            envelope,
            new NativeReadyIdentity(current.SessionId, current.InstanceId, string.Empty));
    }

    private MutationAvailability AvailabilityLocked(
        string commandType,
        bool projectionPermits,
        ConnectionAuthority authority) =>
        MutationAvailability.ForCommand(
            commandType,
            new MutationAuthoritySnapshot(
                _connectionState,
                authority.IsLive,
                authority.AdvertisedCommands,
                projectionPermits
                    && !_workflow.HasPendingCommand
                    && _projectionAuthorityAvailable
                    && _projectionState is not null));

    private bool ProjectionPermitsConversationLocked() =>
        _projectionState?.Composer["can_send"] is NativeJsonBoolean { Value: true };

    private void RefreshMutationAvailability()
    {
        var authority = CaptureConnectionAuthority();
        bool drain;
        lock (_stateLock)
        {
            RefreshMutationAvailabilityLocked(authority);
            drain = EnqueuePresentationLocked(new(null, null, _workflow));
        }
        DrainPresentations(drain);
    }

    private void RefreshMutationAvailabilityLocked(ConnectionAuthority authority)
    {
        _workflow = _workflow.WithAvailability(new MutationAvailabilitySet(
            AvailabilityLocked(ConversationCommands.CommandType, ProjectionPermitsConversationLocked(), authority),
            AvailabilityLocked(ImportCommands.CommandType, true, authority),
            AvailabilityLocked(ApprovalCommands.CommandType, true, authority),
            new MutationAvailability(false, "E_OFFICE_JOB_REQUEST_REQUIRED"),
            AvailabilityLocked(OfficeCommands.SelectCommandType, true, authority),
            AvailabilityLocked(OfficeCommands.OpenCommandType, true, authority),
            AvailabilityLocked(OfficeCommands.CompareCommandType, true, authority),
            new MutationAvailability(false, "E_OFFICE_JOB_REQUEST_REQUIRED"),
            new MutationAvailability(false, "E_OFFICE_JOB_REQUEST_REQUIRED")));
    }

    private void ClearWorkflowAuthority()
    {
        bool drain;
        lock (_stateLock)
        {
            ClearWorkflowAuthorityLocked();
            drain = EnqueuePresentationLocked(new(null, null, _workflow));
        }
        DrainPresentations(drain);
    }

    private void ClearWorkflowAuthorityLocked()
    {
        _workflow = _workflow.ClearAuthority().WithAvailability(MutationAvailabilitySet.None);
        _pendingDraftRevision = null;
    }

    private static string String(NativeJsonObject body, string key) =>
        body[key] is NativeJsonString text
            ? text.Value
            : throw new NativeProtocolError("E_BODY", "command result string is invalid");

    private static long Integer(NativeJsonObject body, string key) =>
        body[key] is NativeJsonInteger { Value: >= 0 } integer
            ? integer.Value
            : throw new NativeProtocolError("E_BODY", "command result cursor is invalid");
}
