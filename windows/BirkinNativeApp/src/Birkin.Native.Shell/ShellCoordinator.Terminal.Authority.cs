using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.Shell;

public sealed partial class ShellCoordinator
{
    private void ClearTerminalAuthorityLocked(bool preserveWorkspaceCwd = false)
    {
        _terminalControls.Clear();
        _approvalCwd = null;
        _pendingCreateCwd = null;
        _terminalWorkflow = _terminalWorkflow.ClearAuthority(preserveWorkspaceCwd);
    }
}
