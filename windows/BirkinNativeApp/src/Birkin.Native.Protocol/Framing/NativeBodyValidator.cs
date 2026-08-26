namespace Birkin.Native.Protocol.Framing;

public enum NativeMessageOrigin
{
    Client,
    Server,
}

public static class NativeBodyValidator
{
    private static readonly HashSet<string> ClientKinds = Set(
        "hello", "subscribe", "command", "ping", "pong", "goodbye");
    private static readonly HashSet<string> ServerKinds = Set(
        "ready", "snapshot", "event", "surface_snapshot", "surface_event", "receipt", "error",
        "capability.renewed", "stream.desynchronized", "ping", "pong", "goodbye");

    public static void Validate(NativeEnvelope envelope, NativeMessageOrigin origin)
    {
        var allowed = origin == NativeMessageOrigin.Client ? ClientKinds : ServerKinds;
        if (!allowed.Contains(envelope.Kind.WireName))
        {
            throw new NativeProtocolError("E_DIRECTION", "message kind came from the wrong endpoint");
        }

        var body = envelope.Body;
        switch (envelope.Kind.WireName)
        {
            case "hello": ValidateHello(body); break;
            case "ready": ValidateReady(body); break;
            case "subscribe":
                Exact(body, "session_id", "after_cursor", "known_instance_id", "session_capability", "surfaces");
                NonNegativeInteger(body, "after_cursor");
                break;
            case "command":
                Exact(body, "session_capability", "command");
                String(body, "session_capability");
                Object(body, "command");
                break;
            case "ping":
            case "pong": ValidateHeartbeat(body, origin); break;
            case "goodbye": ValidateGoodbye(body, origin); break;
            case "snapshot":
                Exact(body, "protocol_version", "session_id", "cursor", "panels", "conversation", "composer",
                    "status", "working_memory", "approval_policy", "terminals", "instance_id", "reset_reason");
                break;
            case "event":
                Exact(body, "protocol_version", "session_id", "cursor", "event_id", "type", "timestamp",
                    "actor_id", "command_id", "payload");
                break;
            case "surface_snapshot":
            case "surface_event":
                Exact(body, "surface", "revision", "payload");
                String(body, "surface");
                NonNegativeInteger(body, "revision");
                Object(body, "payload");
                break;
            case "receipt": ValidateReceipt(body); break;
            case "error": ValidateError(body); break;
            case "capability.renewed":
                Exact(body, "token", "expires_at", "hard_expires_at");
                String(body, "token");
                String(body, "expires_at");
                String(body, "hard_expires_at");
                break;
            case "stream.desynchronized":
                Exact(body, "resume_after");
                NonNegativeInteger(body, "resume_after");
                break;
            default:
                throw new NativeProtocolError("E_KIND", "unsupported native message kind");
        }
    }

    private static void ValidateHello(NativeJsonObject body)
    {
        Exact(body, "client", "client_version", "client_build", "supported_protocol_versions", "surface", "view_id", "bootstrap_secret");
        foreach (var key in new[] { "client", "client_version", "client_build", "surface", "view_id" })
        {
            String(body, key);
        }

        if (body["supported_protocol_versions"] is not NativeJsonArray { Values.Count: > 0 } versions
            || versions.Values.Any(value => value is not NativeJsonInteger))
        {
            throw BodyError();
        }

        if (body["bootstrap_secret"] is not (NativeJsonNull or NativeJsonString))
        {
            throw BodyError();
        }
    }

    private static void ValidateReady(NativeJsonObject body)
    {
        Exact(body, "protocol_version", "server_version", "instance_id", "session_id", "transport", "capability", "limits", "capabilities");
        if (body["protocol_version"] is not NativeJsonInteger { Value: NativeProtocolConstants.Version })
        {
            throw new NativeProtocolError("E_PROTOCOL_VERSION", "ready selected an unsupported native protocol version");
        }

        Exact(Object(body, "capability"), "token", "expires_at", "hard_expires_at");
        Exact(Object(body, "limits"), "max_frame_bytes", "max_payload_bytes", "max_json_depth", "max_inflight_commands", "max_subscriptions");
        Exact(Object(body, "capabilities"), "commands", "panels", "features");
    }

    private static void ValidateHeartbeat(NativeJsonObject body, NativeMessageOrigin origin)
    {
        if (origin == NativeMessageOrigin.Client)
        {
            Exact(body, "session_capability", "sent_at");
            String(body, "session_capability");
        }
        else
        {
            Exact(body, "sent_at");
        }

        String(body, "sent_at");
    }

    private static void ValidateGoodbye(NativeJsonObject body, NativeMessageOrigin origin)
    {
        if (origin == NativeMessageOrigin.Client)
        {
            Exact(body, "session_capability", "reason");
            String(body, "session_capability");
        }
        else
        {
            Exact(body, "reason");
        }

        String(body, "reason");
    }

    private static void ValidateReceipt(NativeJsonObject body)
    {
        var required = Set("protocol_version", "command_id", "session_id", "actor_id", "accepted_cursor", "state", "result_event_cursor", "duplicate", "outcome");
        if (required.Any(key => !body.ContainsKey(key)) || body.Keys.Any(key => !required.Contains(key) && key != "result"))
        {
            throw BodyError();
        }

        String(body, "outcome");
        if (body.ContainsKey("result"))
        {
            Object(body, "result");
        }
    }

    private static void ValidateError(NativeJsonObject body)
    {
        var required = Set("code", "message", "retryable");
        var allowed = Set("code", "message", "retryable", "current_cursor", "current_revision", "limit", "approval_id", "server_protocol_versions", "accepted_cursor", "result_event_cursor");
        if (required.Any(key => !body.ContainsKey(key)) || body.Keys.Any(key => !allowed.Contains(key)))
        {
            throw BodyError();
        }

        String(body, "code");
        String(body, "message");
        if (body["retryable"] is not NativeJsonBoolean)
        {
            throw BodyError();
        }

        if (body.ContainsKey("accepted_cursor") != body.ContainsKey("result_event_cursor"))
        {
            throw BodyError();
        }
        foreach (var key in new[] { "current_cursor", "current_revision", "limit", "accepted_cursor", "result_event_cursor" }.Where(body.ContainsKey))
        {
            NonNegativeInteger(body, key);
        }
        if (body.ContainsKey("approval_id"))
        {
            String(body, "approval_id");
        }
    }

    private static NativeJsonObject Object(NativeJsonObject body, string key) =>
        body[key] as NativeJsonObject ?? throw BodyError();

    private static void String(NativeJsonObject body, string key)
    {
        if (body[key] is not NativeJsonString)
        {
            throw BodyError();
        }
    }

    private static void NonNegativeInteger(NativeJsonObject body, string key)
    {
        if (body[key] is not NativeJsonInteger { Value: >= 0 })
        {
            throw BodyError();
        }
    }

    private static void Exact(NativeJsonObject body, params string[] keys)
    {
        var expected = new HashSet<string>(keys, StringComparer.Ordinal);
        if (body.Count != expected.Count || body.Keys.Any(key => !expected.Contains(key)))
        {
            throw BodyError();
        }
    }

    private static HashSet<string> Set(params string[] values) => new(values, StringComparer.Ordinal);

    private static NativeProtocolError BodyError() => new("E_BODY", "message body does not match the kind schema");
}
