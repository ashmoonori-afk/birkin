using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.Shell;

public sealed partial class ShellCoordinator
{
    private void ResolveTerminalFromCanonicalEventLocked(NativeEnvelope envelope, long currentCursor)
    {
        var type = TerminalString(envelope.Body, "type");
        if (!type.StartsWith("terminal.", StringComparison.Ordinal))
        {
            _terminalWorkflow = _terminalWorkflow.Resolve(string.Empty, false, currentCursor);
            return;
        }
        var commandId = envelope.Body["command_id"] is NativeJsonString command
            ? command.Value
            : string.Empty;
        var payload = TerminalObject(envelope.Body, "payload");
        var exited = string.Equals(type, "terminal.exited", StringComparison.Ordinal);
        if (exited && payload["terminal_id"] is NativeJsonString terminalId)
        {
            _terminalControls.Remove(terminalId.Value);
        }
        _terminalWorkflow = _terminalWorkflow.Resolve(commandId, exited, currentCursor);
    }
}
