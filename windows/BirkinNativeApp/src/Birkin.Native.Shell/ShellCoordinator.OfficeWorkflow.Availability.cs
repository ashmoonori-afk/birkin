using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.Shell;

public sealed partial class ShellCoordinator
{
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
                    && !_terminalWorkflow.HasPendingCommand
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
            drain = EnqueuePresentationLocked(new(null, null, _workflow, _terminalWorkflow));
        }
        DrainPresentations(drain);
    }

    private void RefreshMutationAvailabilityLocked(ConnectionAuthority authority)
    {
        _workflow = _workflow.WithAvailability(new MutationAvailabilitySet(
            AvailabilityLocked(ConversationCommands.CommandType, ProjectionPermitsConversationLocked(), authority),
            AvailabilityLocked(ImportCommands.CommandType, true, authority),
            AvailabilityLocked(ApprovalCommands.CommandType, true, authority),
            AvailabilityLocked(OfficeCommands.CreateCommandType, true, authority),
            AvailabilityLocked(OfficeCommands.SelectCommandType, true, authority),
            AvailabilityLocked(OfficeCommands.OpenCommandType, true, authority),
            AvailabilityLocked(OfficeCommands.CompareCommandType, true, authority),
            AvailabilityLocked(OfficeCommands.DraftCommandType, true, authority),
            AvailabilityLocked(OfficeCommands.ConvertCommandType, true, authority)));
        RefreshTerminalAvailabilityLocked(authority);
    }

    private void ClearWorkflowAuthority()
    {
        bool drain;
        lock (_stateLock)
        {
            ClearWorkflowAuthorityLocked();
            ClearTerminalAuthorityLocked();
            drain = EnqueuePresentationLocked(new(null, null, _workflow, _terminalWorkflow));
        }
        DrainPresentations(drain);
    }

    private void ClearWorkflowAuthorityLocked()
    {
        _workflow = _workflow.ClearAuthority().WithAvailability(MutationAvailabilitySet.None);
        _pendingDraftRevision = null;
    }

}
