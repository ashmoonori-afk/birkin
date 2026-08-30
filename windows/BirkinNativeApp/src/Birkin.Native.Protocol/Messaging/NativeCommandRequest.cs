using Birkin.Native.Protocol.Framing;

namespace Birkin.Native.Protocol.Messaging;

public sealed record NativeCommandIdentity
{
    public NativeCommandIdentity(string commandId, long expectedCursor)
    {
        CommandId = NativeCommandRequest.ValidateIdentifier(commandId, nameof(commandId));
        ArgumentOutOfRangeException.ThrowIfNegative(expectedCursor);
        ExpectedCursor = expectedCursor;
    }

    public string CommandId { get; }
    public long ExpectedCursor { get; }
}

public sealed record NativeCommandIntent
{
    public NativeCommandIntent(string commandType, NativeJsonObject payload)
    {
        CommandType = NativeCommandRequest.ValidateIdentifier(commandType, nameof(commandType));
        Payload = payload;
    }

    public string CommandType { get; }
    public NativeJsonObject Payload { get; }
}

public sealed class NativeCommandRequest
{
    public NativeCommandRequest(NativeCommandIdentity identity, NativeCommandIntent intent, string viewId)
    {
        Identity = identity;
        Intent = intent;
        ViewId = ValidateIdentifier(viewId, nameof(viewId));
    }

    public NativeCommandIdentity Identity { get; }
    public NativeCommandIntent Intent { get; }
    public string ViewId { get; }
    public string CommandId => Identity.CommandId;
    public long ExpectedCursor => Identity.ExpectedCursor;
    public string CommandType => Intent.CommandType;
    public NativeJsonObject Payload => Intent.Payload;

    internal NativeEnvelope CreateEnvelope(string frameId, NativeSessionCapability capability)
    {
        var envelope = new NativeEnvelope(
            NativeMessageKind.Command,
            frameId,
            Object(
                ("session_capability", new NativeJsonString(capability.Token)),
                ("command", Object(
                    ("protocol_version", new NativeJsonInteger(NativeProtocolConstants.Version)),
                    ("command_id", new NativeJsonString(CommandId)),
                    ("expected_cursor", new NativeJsonInteger(ExpectedCursor)),
                    ("type", new NativeJsonString(CommandType)),
                    ("payload", Payload),
                    ("client_context", Object(
                        ("surface", new NativeJsonString("windows")),
                        ("view_id", new NativeJsonString(ViewId))))))));
        NativeBodyValidator.Validate(envelope, NativeMessageOrigin.Client);
        return envelope;
    }

    internal static string ValidateIdentifier(string value, string parameterName)
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

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));
}

public sealed class NativeCommandRefusal : Exception
{
    internal NativeCommandRefusal(
        string code,
        string commandId,
        string message,
        bool retryable,
        long? currentCursor)
        : base(message)
    {
        Code = code;
        CommandId = commandId;
        Retryable = retryable;
        CurrentCursor = currentCursor;
    }

    public string Code { get; }
    public string CommandId { get; }
    public bool Retryable { get; }
    public long? CurrentCursor { get; }
}
