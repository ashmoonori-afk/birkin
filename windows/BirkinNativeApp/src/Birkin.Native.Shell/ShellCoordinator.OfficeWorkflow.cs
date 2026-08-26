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
            drain = EnqueuePresentationLocked(new(null, null, _workflow, _terminalWorkflow));
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

    public Task<bool> CreateOfficeDocumentAsync(
        OfficeCreateIntent intent,
        CancellationToken cancellationToken) =>
        SubmitAsync((_, context) => OfficeCommands.Create(intent, context), false, cancellationToken);

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
        CancellationToken cancellationToken) =>
        SubmitAsync((_, context) => OfficeCommands.Draft(intent, context), false, cancellationToken);

    public Task<bool> ConvertOfficeDocumentAsync(
        OfficeConvertIntent intent,
        CancellationToken cancellationToken) =>
        SubmitAsync((_, context) => OfficeCommands.Convert(intent, context), false, cancellationToken);

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

}
