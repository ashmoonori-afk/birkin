using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.Shell;

public sealed partial class ShellCoordinator
{
    private bool EnqueuePresentationLocked(PresentationUpdate update)
    {
        _presentationQueue.Enqueue(update);
        if (_isDrainingPresentations)
        {
            return false;
        }

        _isDrainingPresentations = true;
        return true;
    }

    private void DrainPresentations(bool drain)
    {
        if (!drain)
        {
            return;
        }

        while (true)
        {
            PresentationUpdate update;
            lock (_stateLock)
            {
                if (!_presentationQueue.TryDequeue(out update!))
                {
                    _isDrainingPresentations = false;
                    return;
                }
            }

            Publish(update);
        }
    }

    private void Publish(PresentationUpdate update)
    {
        if (update.Workspace is { } workspace)
        {
            Action published = () => SnapshotApplied?.Invoke(workspace);
            if (update.Connection is { } readyConnection)
            {
                _presentationModel.PresentReadySnapshot(
                    readyConnection,
                    workspace,
                    update.Workflow,
                    update.TerminalWorkflow,
                    published);
            }
            else
            {
                _presentationModel.PresentSnapshot(
                    workspace,
                    update.Workflow,
                    update.TerminalWorkflow,
                    published);
            }
        }
        else if (update.Connection is { } connection)
        {
            _presentationModel.PresentConnection(
                connection,
                update.Workflow,
                update.TerminalWorkflow);
        }
        else
        {
            _presentationModel.PresentWorkflows(update.Workflow, update.TerminalWorkflow);
        }

        if (update.ChangedConnectionState is { } state)
        {
            ConnectionStateChanged?.Invoke(state);
        }
    }
}
