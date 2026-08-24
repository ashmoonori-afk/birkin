using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Protocol.Projection;

public sealed class NativeProjectionState
{
    private static readonly HashSet<string> SnapshotKeys = new(StringComparer.Ordinal)
    {
        "protocol_version",
        "session_id",
        "cursor",
        "panels",
        "conversation",
        "composer",
        "status",
        "working_memory",
        "approval_policy",
        "terminals",
        "instance_id",
        "reset_reason",
    };

    private static readonly HashSet<string> ResetReasons = new(StringComparer.Ordinal)
    {
        "initial",
        "instance_changed",
        "cursor_ahead",
        "cursor_gap",
    };

    internal NativeProjectionState(NativeJsonObject body, NativeReadyIdentity readyIdentity)
    {
        if (body.Count != SnapshotKeys.Count || body.Keys.Any(key => !SnapshotKeys.Contains(key)))
        {
            throw BodyError();
        }

        ProtocolVersion = body["protocol_version"] is NativeJsonInteger protocolVersion
            && protocolVersion.Value == NativeProtocolConstants.Version
                ? protocolVersion.Value
                : throw new NativeProtocolError("E_PROTOCOL_VERSION", "snapshot selected an unsupported native protocol version");
        SessionId = String(body, "session_id");
        if (!string.Equals(SessionId, readyIdentity.SessionId, StringComparison.Ordinal))
        {
            throw BodyError();
        }

        Cursor = body["cursor"] is NativeJsonInteger { Value: >= 0 } cursor
            ? cursor.Value
            : throw BodyError();
        Panels = ObjectArray(body, "panels");
        Conversation = ObjectArray(body, "conversation");
        Composer = Object(body, "composer");
        Status = Object(body, "status");
        WorkingMemory = Object(body, "working_memory");
        ApprovalPolicy = Object(body, "approval_policy");
        Terminals = ObjectArray(body, "terminals");
        InstanceId = String(body, "instance_id");
        if (!string.Equals(InstanceId, readyIdentity.InstanceId, StringComparison.Ordinal))
        {
            throw BodyError();
        }

        ResetReason = String(body, "reset_reason");
        if (!ResetReasons.Contains(ResetReason))
        {
            throw BodyError();
        }
    }

    public long ProtocolVersion { get; }

    public string SessionId { get; }

    public long Cursor { get; }

    public NativeJsonArray Panels { get; }

    public NativeJsonArray Conversation { get; }

    public NativeJsonObject Composer { get; }

    public NativeJsonObject Status { get; }

    public NativeJsonObject WorkingMemory { get; }

    public NativeJsonObject ApprovalPolicy { get; }

    public NativeJsonArray Terminals { get; }

    public string InstanceId { get; }

    public string ResetReason { get; }

    private static NativeJsonArray ObjectArray(NativeJsonObject body, string key)
    {
        if (body[key] is not NativeJsonArray values || values.Values.Any(value => value is not NativeJsonObject))
        {
            throw BodyError();
        }

        return values;
    }

    private static NativeJsonObject Object(NativeJsonObject body, string key) =>
        body[key] as NativeJsonObject ?? throw BodyError();

    private static string String(NativeJsonObject body, string key) =>
        body[key] is NativeJsonString text ? text.Value : throw BodyError();

    private static NativeProtocolError BodyError() =>
        new("E_BODY", "snapshot body does not match the projection contract");
}
