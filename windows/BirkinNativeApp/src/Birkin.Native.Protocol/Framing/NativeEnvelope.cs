namespace Birkin.Native.Protocol.Framing;

public sealed record NativeEnvelopeIdentity(string Id, string? InReplyTo = null);

public sealed class NativeEnvelope
{
    private static readonly HashSet<string> EnvelopeKeys = new(StringComparer.Ordinal)
    {
        "protocol", "protocol_version", "kind", "id", "in_reply_to", "body",
    };

    public NativeEnvelope(NativeMessageKind kind, string id, NativeJsonObject body)
        : this(kind, new NativeEnvelopeIdentity(id), body)
    {
    }

    public NativeEnvelope(NativeMessageKind kind, NativeEnvelopeIdentity identity, NativeJsonObject body)
    {
        Kind = kind;
        Id = ValidateIdentifier(identity.Id);
        InReplyTo = identity.InReplyTo is null ? null : ValidateIdentifier(identity.InReplyTo);
        Body = body;
        ValidateObject(body, 1);
    }

    public string ProtocolName => NativeProtocolConstants.Name;

    public int ProtocolVersion => NativeProtocolConstants.Version;

    public NativeMessageKind Kind { get; }

    public string Id { get; }

    public string? InReplyTo { get; }

    public NativeJsonObject Body { get; }

    public static NativeEnvelope FromJsonValue(NativeJsonValue value)
    {
        if (value is not NativeJsonObject mapping)
        {
            throw new NativeProtocolError("E_JSON", "envelope must be a JSON object");
        }

        if (mapping.Count != EnvelopeKeys.Count || mapping.Keys.Any(key => !EnvelopeKeys.Contains(key)))
        {
            throw new NativeProtocolError("E_ENVELOPE_KEYS", "native envelope keys do not match the protocol");
        }

        var protocol = RequireString(mapping, "protocol", "E_PROTOCOL");
        if (!string.Equals(protocol, NativeProtocolConstants.Name, StringComparison.Ordinal))
        {
            throw new NativeProtocolError("E_PROTOCOL", "unsupported native protocol");
        }

        if (mapping["protocol_version"] is not NativeJsonInteger version || version.Value != NativeProtocolConstants.Version)
        {
            throw new NativeProtocolError("E_PROTOCOL_VERSION", "unsupported protocol_version");
        }

        var kind = NativeMessageKind.Parse(RequireString(mapping, "kind", "E_KIND"));
        var id = RequireString(mapping, "id", "E_IDENTIFIER");
        var replyValue = mapping["in_reply_to"];
        var reply = replyValue switch
        {
            NativeJsonNull => null,
            NativeJsonString text => text.Value,
            _ => throw new NativeProtocolError("E_IDENTIFIER", "in_reply_to must be a bounded identifier"),
        };
        if (mapping["body"] is not NativeJsonObject body)
        {
            throw new NativeProtocolError("E_JSON", "body must be a JSON object");
        }

        return new NativeEnvelope(kind, new NativeEnvelopeIdentity(id, reply), body);
    }

    public NativeJsonObject ToJsonValue() => new(
        new KeyValuePair<string, NativeJsonValue>[]
        {
            new("protocol", new NativeJsonString(ProtocolName)),
            new("protocol_version", new NativeJsonInteger(ProtocolVersion)),
            new("kind", new NativeJsonString(Kind.WireName)),
            new("id", new NativeJsonString(Id)),
            new("in_reply_to", InReplyTo is null ? NativeJsonNull.Value : new NativeJsonString(InReplyTo)),
            new("body", Body),
        });

    private static string RequireString(NativeJsonObject mapping, string key, string code) =>
        mapping[key] is NativeJsonString text
            ? text.Value
            : throw new NativeProtocolError(code, $"{key} must be a string");

    private static string ValidateIdentifier(string value)
    {
        if (value.Length is < 1 or > 128 || value.Any(character =>
            character is not (>= 'A' and <= 'Z')
            and not (>= 'a' and <= 'z')
            and not (>= '0' and <= '9')
            and not '.' and not '_' and not ':' and not '-'))
        {
            throw new NativeProtocolError("E_IDENTIFIER", "identifier must be a bounded identifier");
        }

        return value;
    }

    private static void ValidateObject(NativeJsonObject obj, int depth)
    {
        if (depth > NativeProtocolConstants.MaxBodyDepth)
        {
            throw new NativeProtocolError("E_JSON_DEPTH", "JSON exceeds maximum depth");
        }

        foreach (var pair in obj.Pairs)
        {
            ValidateValue(pair.Value, depth + 1);
        }
    }

    private static void ValidateValue(NativeJsonValue value, int depth)
    {
        if (depth > NativeProtocolConstants.MaxBodyDepth)
        {
            throw new NativeProtocolError("E_JSON_DEPTH", "JSON exceeds maximum depth");
        }

        switch (value)
        {
            case NativeJsonArray array:
                foreach (var element in array.Values)
                {
                    ValidateValue(element, depth + 1);
                }
                break;
            case NativeJsonObject obj:
                ValidateObject(obj, depth);
                break;
        }
    }
}
