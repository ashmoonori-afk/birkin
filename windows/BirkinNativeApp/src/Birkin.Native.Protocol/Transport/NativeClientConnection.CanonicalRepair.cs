using System.Net.Sockets;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;

namespace Birkin.Native.Protocol.Transport;

public sealed partial class NativeClientConnection
{
    private async Task HandleLifecycleFrameAsync(NativeEnvelope envelope, CancellationToken cancellationToken)
    {
        switch (envelope.Kind.WireName)
        {
            case "ping":
                var capability = CurrentCapability
                    ?? throw new NativeProtocolError("E_CAPABILITY_EXPIRED", "session capability is unavailable");
                var pong = NativeHandshake.CreatePong(envelope, capability, NextId());
                Claim(pong.Id);
                await (_transport ?? throw new NativeProtocolError("E_STATE", "connection is not active"))
                    .SendAsync(pong, cancellationToken).ConfigureAwait(false);
                break;
            case "capability.renewed":
                ReplaceCapability(NativeHandshake.ValidateRenewedCapability(envelope));
                break;
            case "stream.desynchronized":
                if (!_canonicalRepairManagedExternally)
                {
                    _projectionStore.ApplyStreamSignal(envelope);
                    if (_projectionStore.TryBeginReplay())
                    {
                        var resumeAfter = envelope.Body["resume_after"] is NativeJsonInteger cursor
                            ? cursor.Value
                            : throw new NativeProtocolError("E_BODY", "resume cursor is invalid");
                        await RequestCanonicalReplayAsync(resumeAfter, cancellationToken).ConfigureAwait(false);
                    }
                }
                break;
            case "snapshot":
                IsProjectionCurrent = true;
                break;
            case "goodbye":
                await DisconnectAsync().ConfigureAwait(false);
                break;
            case "error":
                if (envelope.Body["code"] is NativeJsonString { Value: "E_CAPABILITY_EXPIRED" }) ClearAuthority();
                break;
            case "event":
            case "surface_snapshot":
            case "surface_event":
            case "receipt":
            case "pong":
                break;
            default:
                throw new NativeProtocolError("E_STATE", "server frame is not valid during a subscribed session");
        }
    }

    internal void UseExternalCanonicalRepairOwner() => _canonicalRepairManagedExternally = true;

    internal async ValueTask RequestCanonicalReplayAsync(
        long afterCursor,
        CancellationToken cancellationToken)
    {
        IsProjectionCurrent = false;
        var session = _session ?? throw new NativeProtocolError("E_STATE", "connection session is unavailable");
        var revisions = _projectionStore.SurfaceRevisions.ToDictionary(
            pair => pair.Key,
            _ => 0L,
            StringComparer.Ordinal);
        var repair = new NativeProjectionSubscription(
            afterCursor,
            session.InstanceId,
            revisions,
            isCanonicalRepair: true);
        var subscribe = NativeHandshake.CreateSubscribe(session, NextId(), repair);
        Claim(subscribe.Id);
        await (_transport ?? throw new NativeProtocolError("E_STATE", "connection is not active"))
            .SendAsync(subscribe, cancellationToken).ConfigureAwait(false);
    }

    internal async ValueTask RequestCanonicalSnapshotAsync(CancellationToken cancellationToken)
    {
        IsProjectionCurrent = false;
        var session = _session ?? throw new NativeProtocolError("E_STATE", "connection session is unavailable");
        var subscribe = NativeHandshake.CreateSubscribe(session, NextId());
        Claim(subscribe.Id);
        await (_transport ?? throw new NativeProtocolError("E_STATE", "connection is not active"))
            .SendAsync(subscribe, cancellationToken).ConfigureAwait(false);
    }

}
