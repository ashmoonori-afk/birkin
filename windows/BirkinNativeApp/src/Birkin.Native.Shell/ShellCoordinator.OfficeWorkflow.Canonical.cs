using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.Shell;

public sealed partial class ShellCoordinator
{
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

}
