using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.Shell;

public sealed partial class ShellCoordinator
{
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
            drain = EnqueuePresentationLocked(new(null, null, _workflow, _terminalWorkflow));
        }
        DrainPresentations(drain);
    }

    private void Refuse(NativeCommandRefusal refusal)
    {
        var authority = CaptureConnectionAuthority();
        bool drain;
        lock (_stateLock)
        {
            _workflow = _workflow.Refuse(refusal.CommandId, refusal.Code, refusal.CurrentCursor, refusal.Message);
            if (string.Equals(_workflow.CommandId, refusal.CommandId, StringComparison.Ordinal))
            {
                _pendingDraftRevision = null;
            }
            RefreshMutationAvailabilityLocked(authority);
            drain = EnqueuePresentationLocked(new(null, null, _workflow, _terminalWorkflow));
        }
        DrainPresentations(drain);
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
