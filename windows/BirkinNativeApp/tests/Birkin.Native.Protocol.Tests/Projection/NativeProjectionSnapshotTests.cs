using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Projection;

[TestClass]
public sealed class NativeProjectionSnapshotTests
{
    private static readonly NativeReadyIdentity ReadyIdentity = new("session-1", "instance-1", "0.4.276");

    [TestMethod]
    public void ApplySnapshot_WhenSnapshotIsValid_ReplacesStateAndPublishesAfterReplacement()
    {
        // Given
        var store = new NativeProjectionStore();
        var snapshot = Snapshot();
        NativeProjectionState? published = null;
        store.SnapshotApplied += state =>
        {
            Assert.AreSame(state, store.State);
            published = state;
        };

        // When
        store.ApplySnapshot(snapshot, ReadyIdentity);

        // Then
        var state = store.State;
        Assert.IsNotNull(state);
        Assert.AreSame(state, published);
        Assert.AreEqual(1L, state.ProtocolVersion);
        Assert.AreEqual("session-1", state.SessionId);
        Assert.AreEqual(2L, state.Cursor);
        Assert.AreSame(snapshot.Body["panels"], state.Panels);
        Assert.AreSame(snapshot.Body["conversation"], state.Conversation);
        Assert.AreSame(snapshot.Body["composer"], state.Composer);
        Assert.AreSame(snapshot.Body["status"], state.Status);
        Assert.AreSame(snapshot.Body["working_memory"], state.WorkingMemory);
        Assert.AreSame(snapshot.Body["approval_policy"], state.ApprovalPolicy);
        Assert.AreSame(snapshot.Body["terminals"], state.Terminals);
        Assert.AreEqual("instance-1", state.InstanceId);
        Assert.AreEqual("initial", state.ResetReason);
    }

    [TestMethod]
    public void ApplySnapshot_WhenEnvelopeKindIsNotSnapshot_RefusesWithoutPublishing()
    {
        // Given
        var store = new NativeProjectionStore();
        var published = false;
        store.SnapshotApplied += _ => published = true;
        var envelope = new NativeEnvelope(NativeMessageKind.Event, "server-1", Snapshot().Body);

        // When
        var error = Assert.ThrowsException<NativeProtocolError>(() => store.ApplySnapshot(envelope, ReadyIdentity));

        // Then
        Assert.AreEqual("E_STATE", error.Code);
        Assert.IsNull(store.State);
        Assert.IsFalse(published);
    }

    [DataTestMethod]
    [DataRow("protocol_version", "E_PROTOCOL_VERSION")]
    [DataRow("session_id", "E_BODY")]
    [DataRow("cursor", "E_BODY")]
    [DataRow("panels", "E_BODY")]
    [DataRow("conversation", "E_BODY")]
    [DataRow("composer", "E_BODY")]
    [DataRow("status", "E_BODY")]
    [DataRow("working_memory", "E_BODY")]
    [DataRow("approval_policy", "E_BODY")]
    [DataRow("terminals", "E_BODY")]
    [DataRow("instance_id", "E_BODY")]
    [DataRow("reset_reason", "E_BODY")]
    public void ApplySnapshot_WhenRequiredValueIsInvalid_LeavesPreviousStateUntouched(string key, string code)
    {
        // Given
        var store = new NativeProjectionStore();
        store.ApplySnapshot(Snapshot(), ReadyIdentity);
        var previous = store.State;
        var published = false;
        store.SnapshotApplied += _ => published = true;
        var invalid = Snapshot(InvalidValue(key));

        // When
        var error = Assert.ThrowsException<NativeProtocolError>(() => store.ApplySnapshot(invalid, ReadyIdentity));

        // Then
        Assert.AreEqual(code, error.Code);
        Assert.AreSame(previous, store.State);
        Assert.IsFalse(published);
    }

    [DataTestMethod]
    [DataRow(true)]
    [DataRow(false)]
    public void ApplySnapshot_WhenBodyKeysAreNotExact_RefusesWithStableCode(bool addUnexpectedKey)
    {
        // Given
        var pairs = Snapshot().Body.Pairs.ToList();
        if (addUnexpectedKey)
        {
            pairs.Add(new("unexpected", NativeJsonNull.Value));
        }
        else
        {
            pairs.RemoveAll(pair => pair.Key == "terminals");
        }
        var store = new NativeProjectionStore();
        var snapshot = new NativeEnvelope(NativeMessageKind.Snapshot, "server-2", new NativeJsonObject(pairs));

        // When
        var error = Assert.ThrowsException<NativeProtocolError>(() => store.ApplySnapshot(snapshot, ReadyIdentity));

        // Then
        Assert.AreEqual("E_BODY", error.Code);
        Assert.IsNull(store.State);
    }

    private static (string Key, NativeJsonValue Value) InvalidValue(string key) => key switch
    {
        "protocol_version" => (key, new NativeJsonInteger(2)),
        "session_id" => (key, new NativeJsonString("other-session")),
        "cursor" => (key, new NativeJsonInteger(-1)),
        "panels" or "conversation" or "terminals" => (key, new NativeJsonObject()),
        "composer" or "status" or "working_memory" or "approval_policy" => (key, new NativeJsonArray([])),
        "instance_id" => (key, new NativeJsonString("other-instance")),
        "reset_reason" => (key, new NativeJsonString("unknown")),
        _ => throw new InvalidOperationException(),
    };

    private static NativeEnvelope Snapshot((string Key, NativeJsonValue Value)? replacement = null)
    {
        var values = new (string Key, NativeJsonValue Value)[]
        {
            ("protocol_version", new NativeJsonInteger(1)),
            ("session_id", new NativeJsonString("session-1")),
            ("cursor", new NativeJsonInteger(2)),
            ("panels", new NativeJsonArray([Object(("key", new NativeJsonString("tasks_runs")), ("items", new NativeJsonArray([])))])),
            ("conversation", new NativeJsonArray([Object(("id", new NativeJsonString("event-1")))])),
            ("composer", Object(("can_send", new NativeJsonBoolean(true)))),
            ("status", Object(("connection", new NativeJsonString("connected")))),
            ("working_memory", Object(("revision", new NativeJsonInteger(1)))),
            ("approval_policy", Object(("pending_requests", new NativeJsonArray([])))),
            ("terminals", new NativeJsonArray([])),
            ("instance_id", new NativeJsonString("instance-1")),
            ("reset_reason", new NativeJsonString("initial")),
        };
        if (replacement is { } item)
        {
            var index = Array.FindIndex(values, pair => pair.Key == item.Key);
            values[index] = item;
        }
        return new NativeEnvelope(NativeMessageKind.Snapshot, "server-1", Object(values));
    }

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));
}
