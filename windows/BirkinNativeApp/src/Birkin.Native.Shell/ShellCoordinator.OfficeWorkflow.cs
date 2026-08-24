using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.Shell;

public sealed partial class ShellCoordinator
{
    private const int MaxFramesBeforeCommandResult = 128;
    private OfficeWorkflowPresentation _workflow = OfficeWorkflowPresentation.Empty;

    private sealed record CommandSubmission(NativeCommandRequest Request, bool ProjectionPermits);

    public void SetConversationDraft(string draft)
    {
        _workflow = _workflow.WithDraft(draft);
        PresentWorkflow();
    }

    public Task<bool> SendConversationAsync(CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(_workflow.Draft))
        {
            return Task.FromResult(false);
        }

        return SubmitAsync(
            new CommandSubmission(
                ConversationCommands.Send(_workflow.Draft, Context("conversation")),
                ProjectionPermitsConversation()),
            cancellationToken);
    }

    public Task<bool> ImportAsync(FileImportIntent intent, CancellationToken cancellationToken) =>
        SubmitAsync(
            new CommandSubmission(ImportCommands.Import(intent, Context("imports")), true),
            cancellationToken);

    public Task<bool> AnswerApprovalAsync(
        ApprovalAnswerIntent intent,
        CancellationToken cancellationToken) =>
        SubmitAsync(
            new CommandSubmission(ApprovalCommands.Answer(intent, Context("approvals")), true),
            cancellationToken);

    public Task<bool> CreateOfficeDocumentAsync(
        OfficeCreateIntent intent,
        CancellationToken cancellationToken) =>
        SubmitAsync(
            new CommandSubmission(OfficeCommands.Create(intent, Context("office")), true),
            cancellationToken);

    public Task<bool> SelectOfficeDocumentAsync(
        OfficeSelectIntent intent,
        CancellationToken cancellationToken) =>
        SubmitAsync(
            new CommandSubmission(OfficeCommands.Select(intent, Context("office")), true),
            cancellationToken);

    public Task<bool> OpenOfficeDocumentAsync(
        OfficeOpenIntent intent,
        CancellationToken cancellationToken) =>
        SubmitAsync(
            new CommandSubmission(OfficeCommands.Open(intent, Context("office")), true),
            cancellationToken);

    public Task<bool> ConvertOfficeDocumentAsync(
        OfficeConvertIntent intent,
        CancellationToken cancellationToken) =>
        SubmitAsync(
            new CommandSubmission(OfficeCommands.Convert(intent, Context("office")), true),
            cancellationToken);

    public async Task ReceiveCanonicalAsync(CancellationToken cancellationToken)
    {
        var envelope = await _connection.ReceiveAsync(cancellationToken).ConfigureAwait(false);
        ApplyCanonicalFrame(envelope);
    }

    private async Task<bool> SubmitAsync(
        CommandSubmission submission,
        CancellationToken cancellationToken)
    {
        var request = submission.Request;
        var availability = Availability(request.CommandType, submission.ProjectionPermits);
        if (!availability.IsEnabled || _workflow.HasPendingCommand)
        {
            if (!_connection.HasLiveCapability(DateTimeOffset.UtcNow))
            {
                ClearWorkflowAuthority();
            }
            else
            {
                RefreshMutationAvailability();
            }
            return false;
        }

        _workflow = _workflow.Begin(request.CommandId, request.CommandType);
        RefreshMutationAvailability();
        try
        {
            await _connection.SendCommandAsync(request, cancellationToken).ConfigureAwait(false);
            return await ReceiveCommandResultAsync(request.CommandId, cancellationToken).ConfigureAwait(false);
        }
        catch (NativeCommandRefusal refusal)
        {
            _workflow = _workflow.Refuse(refusal.CommandId, refusal.Code, refusal.CurrentCursor);
            RefreshMutationAvailability();
            return false;
        }
        catch (NativeProtocolError) when (!_connection.HasLiveCapability(DateTimeOffset.UtcNow))
        {
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
                ResolveFromCanonicalEvent(envelope);
                PresentProjection();
                break;
            case "surface_snapshot":
            case "surface_event":
                _projectionStore.ApplySurface(envelope);
                PresentProjection();
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
        _workflow = _workflow.Accept(commandId, acceptedCursor);
        RefreshMutationAvailability();
    }

    private void ResolveFromCanonicalEvent(NativeEnvelope envelope)
    {
        if (envelope.Body["command_id"] is NativeJsonString commandId)
        {
            _workflow = _workflow.ResolveFromProjection(commandId.Value);
            PresentWorkflow();
        }
    }

    private void ApplyCanonicalSnapshot(NativeEnvelope envelope)
    {
        var current = _projectionStore.State
            ?? throw new NativeProtocolError("E_STATE", "replacement snapshot requires canonical identity");
        _projectionStore.ApplySnapshot(
            envelope,
            new NativeReadyIdentity(current.SessionId, current.InstanceId, string.Empty));
    }

    private void PresentProjection()
    {
        if (_projectionStore.State is not { } state)
        {
            return;
        }

        var snapshot = WorkspaceSnapshotPresentation.FromProjection(state, "loopback");
        _presentationModel.PresentSnapshot(snapshot, () => SnapshotApplied?.Invoke(snapshot));
        RefreshMutationAvailability();
    }

    private CommandRequestContext Context(string viewId) => new(
        CommandIdFactory(),
        _projectionStore.State?.Cursor ?? 0,
        viewId);

    private MutationAvailability Availability(string commandType, bool projectionPermits) =>
        MutationAvailability.ForCommand(
            commandType,
            new MutationAuthoritySnapshot(
                _connectionState,
                _connection.HasLiveCapability(DateTimeOffset.UtcNow),
                _connection.AdvertisedCommands,
                projectionPermits
                    && !_workflow.HasPendingCommand
                    && _projectionStore.Status == Protocol.Projection.NativeProjectionStoreStatus.Current));

    private bool ProjectionPermitsConversation() =>
        _projectionStore.State?.Composer["can_send"] is NativeJsonBoolean { Value: true };

    private void RefreshMutationAvailability()
    {
        _workflow = _workflow.WithAvailability(new MutationAvailabilitySet(
            Availability(ConversationCommands.CommandType, ProjectionPermitsConversation()),
            Availability(ImportCommands.CommandType, true),
            Availability(ApprovalCommands.CommandType, true),
            Availability(OfficeCommands.CreateCommandType, true),
            Availability(OfficeCommands.SelectCommandType, true),
            Availability(OfficeCommands.OpenCommandType, true),
            Availability(OfficeCommands.ConvertCommandType, true)));
        PresentWorkflow();
    }

    private void ClearWorkflowAuthority()
    {
        _workflow = _workflow.ClearAuthority().WithAvailability(MutationAvailabilitySet.None);
        PresentWorkflow();
    }

    private void PresentWorkflow() => _presentationModel.PresentOfficeWorkflow(_workflow);

    private static string String(NativeJsonObject body, string key) =>
        body[key] is NativeJsonString text
            ? text.Value
            : throw new NativeProtocolError("E_BODY", "command result string is invalid");

    private static long Integer(NativeJsonObject body, string key) =>
        body[key] is NativeJsonInteger { Value: >= 0 } integer
            ? integer.Value
            : throw new NativeProtocolError("E_BODY", "command result cursor is invalid");
}
