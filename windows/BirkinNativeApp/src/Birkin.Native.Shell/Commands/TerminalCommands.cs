using System.Text;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Shell.Commands;

public sealed record TerminalCreateIntent(string ActorKind, string Cwd, string? ApprovalId);
public sealed record TerminalInputIntent(string TerminalId, string Lease, long Sequence, string Data);
public sealed record TerminalResizeIntent(string TerminalId, string Lease, long Columns, long Rows);
public sealed record TerminalSignalIntent(string TerminalId, string Lease, string Signal);
public sealed record TerminalCloseIntent(string TerminalId, string Lease);

public static class TerminalCommands
{
    public const string CreateCommandType = "terminal.create";
    public const string InputCommandType = "terminal.input";
    public const string ResizeCommandType = "terminal.resize";
    public const string SignalCommandType = "terminal.signal";
    public const string CloseCommandType = "terminal.close";

    public static NativeCommandRequest Create(TerminalCreateIntent intent, CommandRequestContext context)
    {
        if (!string.Equals(intent.ActorKind, "native_human", StringComparison.Ordinal))
        {
            throw new ArgumentException("Terminal actor must be native_human.", nameof(intent));
        }
        if (string.IsNullOrWhiteSpace(intent.Cwd))
        {
            throw new ArgumentException("Terminal cwd must be specified.", nameof(intent));
        }

        var payload = new List<KeyValuePair<string, NativeJsonValue>>
        {
            new("actor_kind", new NativeJsonString(intent.ActorKind)),
            new("cwd", new NativeJsonString(intent.Cwd)),
        };
        if (intent.ApprovalId is { } approvalId)
        {
            payload.Add(new("approval_id", new NativeJsonString(Identifier(approvalId, nameof(intent.ApprovalId)))));
        }
        return Request(CreateCommandType, new NativeJsonObject(payload), context);
    }

    public static NativeCommandRequest Input(TerminalInputIntent intent, CommandRequestContext context)
    {
        Identifier(intent.TerminalId, nameof(intent.TerminalId));
        Identifier(intent.Lease, nameof(intent.Lease));
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(intent.Sequence);
        if (string.IsNullOrEmpty(intent.Data) || Utf8Length(intent.Data) > 4096)
        {
            throw new ArgumentException("Terminal input must contain at most 4096 UTF-8 bytes.", nameof(intent));
        }
        return Request(InputCommandType, Object(
            ("terminal_id", new NativeJsonString(intent.TerminalId)),
            ("lease", new NativeJsonString(intent.Lease)),
            ("sequence", new NativeJsonInteger(intent.Sequence)),
            ("data", new NativeJsonString(intent.Data))), context);
    }

    public static NativeCommandRequest Resize(TerminalResizeIntent intent, CommandRequestContext context)
    {
        Identifier(intent.TerminalId, nameof(intent.TerminalId));
        Identifier(intent.Lease, nameof(intent.Lease));
        Dimension(intent.Columns, nameof(intent.Columns));
        Dimension(intent.Rows, nameof(intent.Rows));
        return Request(ResizeCommandType, Object(
            ("terminal_id", new NativeJsonString(intent.TerminalId)),
            ("lease", new NativeJsonString(intent.Lease)),
            ("columns", new NativeJsonInteger(intent.Columns)),
            ("rows", new NativeJsonInteger(intent.Rows))), context);
    }

    public static NativeCommandRequest Signal(TerminalSignalIntent intent, CommandRequestContext context)
    {
        Identifier(intent.TerminalId, nameof(intent.TerminalId));
        Identifier(intent.Lease, nameof(intent.Lease));
        if (!string.Equals(intent.Signal, "INT", StringComparison.Ordinal))
        {
            throw new ArgumentException("Terminal signal must be INT.", nameof(intent));
        }
        return Request(SignalCommandType, Object(
            ("terminal_id", new NativeJsonString(intent.TerminalId)),
            ("lease", new NativeJsonString(intent.Lease)),
            ("signal", new NativeJsonString(intent.Signal))), context);
    }

    public static NativeCommandRequest Close(TerminalCloseIntent intent, CommandRequestContext context)
    {
        Identifier(intent.TerminalId, nameof(intent.TerminalId));
        Identifier(intent.Lease, nameof(intent.Lease));
        return Request(CloseCommandType, Object(
            ("terminal_id", new NativeJsonString(intent.TerminalId)),
            ("lease", new NativeJsonString(intent.Lease))), context);
    }

    private static NativeCommandRequest Request(
        string commandType,
        NativeJsonObject payload,
        CommandRequestContext context) => new(
            new NativeCommandIdentity(context.CommandId, context.ExpectedCursor),
            new NativeCommandIntent(commandType, payload),
            context.ViewId);

    private static string Identifier(string value, string parameterName)
    {
        if (value.Length is < 1 or > 128
            || value is "." or ".."
            || value.Any(character =>
                character is not (>= 'A' and <= 'Z')
                and not (>= 'a' and <= 'z')
                and not (>= '0' and <= '9')
                and not '.' and not '_' and not ':' and not '-'))
        {
            throw new ArgumentException("value must be a bounded protocol identifier", parameterName);
        }
        return value;
    }

    private static void Dimension(long value, string parameterName)
    {
        if (value is < 1 or > 1000)
        {
            throw new ArgumentOutOfRangeException(parameterName, "Terminal dimensions must be between 1 and 1000.");
        }
    }

    private static int Utf8Length(string value)
    {
        try
        {
            return new UTF8Encoding(false, true).GetByteCount(value);
        }
        catch (EncoderFallbackException error)
        {
            throw new ArgumentException("Terminal input must be valid UTF-8.", nameof(value), error);
        }
    }

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));
}
