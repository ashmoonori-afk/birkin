using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.Shell;

public sealed partial class ShellCoordinator
{
    private void TransitionTo(ConnectionState state)
    {
        var authority = CaptureConnectionAuthority();
        bool drain;
        lock (_stateLock)
        {
            _connectionState = state;
            if (state != ConnectionState.Ready)
            {
                ClearTerminalAuthorityLocked();
            }
            RefreshMutationAvailabilityLocked(authority);
            drain = EnqueuePresentationLocked(new(
                ConnectionPresentation.Create(state),
                null,
                _workflow,
                _terminalWorkflow,
                state));
        }
        DrainPresentations(drain);
    }

    private void Fail(string errorCode)
    {
        bool drain;
        lock (_stateLock)
        {
            _connectionState = ConnectionState.Failed;
            ClearWorkflowAuthorityLocked();
            ClearTerminalAuthorityLocked();
            drain = EnqueuePresentationLocked(new(
                ConnectionPresentation.Failed(errorCode),
                null,
                _workflow,
                _terminalWorkflow,
                ConnectionState.Failed));
        }
        DrainPresentations(drain);
    }

    private ConnectionAuthority CaptureConnectionAuthority() => new(
        _connection.HasLiveCapability(DateTimeOffset.UtcNow),
        new HashSet<string>(_connection.AdvertisedCommands, StringComparer.Ordinal));

    private long ReserveProjectionCallbackSequence()
    {
        lock (_stateLock)
        {
            return ++_nextProjectionCallbackSequence;
        }
    }

}
