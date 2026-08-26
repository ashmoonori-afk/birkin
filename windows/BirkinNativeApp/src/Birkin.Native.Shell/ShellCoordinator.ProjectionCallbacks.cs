using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.Shell;

public sealed partial class ShellCoordinator
{
    private void OnProjectionSnapshotApplied(NativeProjectionState state)
    {
        var callbackSequence = ReserveProjectionCallbackSequence();
        var snapshot = WorkspaceSnapshotPresentation.FromProjection(state, "loopback");
        var authority = CaptureConnectionAuthority();
        bool drain;
        lock (_stateLock)
        {
            _projectionState = state;
            ClearTerminalAuthorityLocked(preserveWorkspaceCwd: true);
            if (callbackSequence > _lastAuthorityCallbackSequence)
            {
                _projectionAuthorityAvailable = true;
                _lastAuthorityCallbackSequence = callbackSequence;
            }
            _connectionState = ConnectionState.Ready;
            RefreshMutationAvailabilityLocked(authority);
            drain = EnqueuePresentationLocked(new(
                ConnectionPresentation.Create(ConnectionState.Ready),
                snapshot,
                _workflow,
                _terminalWorkflow,
                ConnectionState.Ready));
        }
        DrainPresentations(drain);
    }

    private void OnCanonicalApplied(NativeEnvelope envelope)
    {
        var callbackSequence = ReserveProjectionCallbackSequence();
        var state = _projectionStore.State;
        if (state is null)
        {
            return;
        }

        var projectionAuthorityAvailable = _projectionStore.IsMutationAuthorityAvailable;
        var snapshot = WorkspaceSnapshotPresentation.FromProjection(state, "loopback");
        var authority = CaptureConnectionAuthority();
        bool drain;
        lock (_stateLock)
        {
            _projectionState = state;
            if (callbackSequence > _lastAuthorityCallbackSequence)
            {
                _projectionAuthorityAvailable = projectionAuthorityAvailable;
                _lastAuthorityCallbackSequence = callbackSequence;
            }
            if (envelope.Kind == NativeMessageKind.Event)
            {
                ResolveFromCanonicalEventLocked(envelope);
                var canonicalCursor = envelope.Body["cursor"] is NativeJsonInteger cursor
                    ? cursor.Value
                    : state.Cursor;
                ResolveTerminalFromCanonicalEventLocked(envelope, canonicalCursor);
            }
            RefreshMutationAvailabilityLocked(authority);
            drain = EnqueuePresentationLocked(new(null, snapshot, _workflow, _terminalWorkflow));
        }
        DrainPresentations(drain);
    }

    private void OnMutationAuthorityChanged(bool available)
    {
        var callbackSequence = ReserveProjectionCallbackSequence();
        var authority = CaptureConnectionAuthority();
        bool drain;
        lock (_stateLock)
        {
            if (callbackSequence <= _lastAuthorityCallbackSequence)
            {
                return;
            }

            _lastAuthorityCallbackSequence = callbackSequence;
            _projectionAuthorityAvailable = available;
            if (available)
            {
                RefreshMutationAvailabilityLocked(authority);
            }
            else
            {
                ClearWorkflowAuthorityLocked();
                ClearTerminalAuthorityLocked();
                RefreshTerminalAvailabilityLocked(authority);
            }
            drain = EnqueuePresentationLocked(new(null, null, _workflow, _terminalWorkflow));
        }
        DrainPresentations(drain);
    }

}
