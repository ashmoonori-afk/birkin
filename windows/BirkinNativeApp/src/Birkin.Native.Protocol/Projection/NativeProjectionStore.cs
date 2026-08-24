using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Protocol.Projection;

/// <summary>Owns the latest validated Python workspace snapshot in memory.</summary>
public sealed class NativeProjectionStore
{
    public NativeProjectionState? State { get; private set; }

    public event Action<NativeProjectionState>? SnapshotApplied;

    public void ApplySnapshot(NativeEnvelope envelope, NativeReadyIdentity readyIdentity)
    {
        if (envelope.Kind != NativeMessageKind.Snapshot)
        {
            throw new NativeProtocolError("E_STATE", "projection application requires a snapshot envelope");
        }

        var replacement = new NativeProjectionState(envelope.Body, readyIdentity);
        State = replacement;
        SnapshotApplied?.Invoke(replacement);
    }
}
