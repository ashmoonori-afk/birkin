using System.Collections.ObjectModel;

namespace Birkin.Native.Protocol.Framing;

public enum NativeJsonKind
{
    Null,
    Boolean,
    Integer,
    Float,
    String,
    Array,
    Object,
}

public abstract record NativeJsonValue
{
    public abstract NativeJsonKind Kind { get; }
}

public sealed record NativeJsonNull : NativeJsonValue
{
    private NativeJsonNull()
    {
    }

    public static NativeJsonNull Value { get; } = new();

    public override NativeJsonKind Kind => NativeJsonKind.Null;
}

public sealed record NativeJsonBoolean(bool Value) : NativeJsonValue
{
    public override NativeJsonKind Kind => NativeJsonKind.Boolean;
}

public sealed record NativeJsonInteger(long Value) : NativeJsonValue
{
    public override NativeJsonKind Kind => NativeJsonKind.Integer;
}

public sealed record NativeJsonFloat : NativeJsonValue
{
    public NativeJsonFloat(double value)
    {
        if (!double.IsFinite(value))
        {
            throw new NativeProtocolError("E_NONFINITE_NUMBER", "JSON contains a non-finite number");
        }

        Value = value;
    }

    public double Value { get; }

    public override NativeJsonKind Kind => NativeJsonKind.Float;
}

public sealed record NativeJsonString(string Value) : NativeJsonValue
{
    public override NativeJsonKind Kind => NativeJsonKind.String;
}

public sealed record NativeJsonArray : NativeJsonValue
{
    public NativeJsonArray(IEnumerable<NativeJsonValue> values)
    {
        Values = Array.AsReadOnly(values.ToArray());
    }

    public IReadOnlyList<NativeJsonValue> Values { get; }

    public override NativeJsonKind Kind => NativeJsonKind.Array;
}

public sealed record NativeJsonObject : NativeJsonValue
{
    private readonly IReadOnlyDictionary<string, NativeJsonValue> _values;

    public NativeJsonObject()
        : this(Array.Empty<KeyValuePair<string, NativeJsonValue>>())
    {
    }

    public NativeJsonObject(IEnumerable<KeyValuePair<string, NativeJsonValue>> pairs)
    {
        var ordered = pairs.ToArray();
        var values = new Dictionary<string, NativeJsonValue>(StringComparer.Ordinal);
        foreach (var pair in ordered)
        {
            if (!values.TryAdd(pair.Key, pair.Value))
            {
                throw new NativeProtocolError("E_DUPLICATE_KEY", "JSON object contains a duplicate key");
            }
        }

        Pairs = Array.AsReadOnly(ordered);
        Keys = Array.AsReadOnly(ordered.Select(pair => pair.Key).ToArray());
        _values = new ReadOnlyDictionary<string, NativeJsonValue>(values);
    }

    public IReadOnlyList<KeyValuePair<string, NativeJsonValue>> Pairs { get; }

    public IReadOnlyList<string> Keys { get; }

    public int Count => Pairs.Count;

    public override NativeJsonKind Kind => NativeJsonKind.Object;

    public NativeJsonValue? this[string key] => _values.GetValueOrDefault(key);

    public bool ContainsKey(string key) => _values.ContainsKey(key);
}
