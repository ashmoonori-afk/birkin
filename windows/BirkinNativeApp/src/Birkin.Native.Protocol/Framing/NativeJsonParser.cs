using System.Text;
using System.Text.Json;

namespace Birkin.Native.Protocol.Framing;

public static class NativeJsonParser
{
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);

    public static NativeJsonValue Parse(ReadOnlySpan<byte> utf8)
    {
        try
        {
            _ = StrictUtf8.GetCharCount(utf8);
        }
        catch (DecoderFallbackException)
        {
            throw new NativeProtocolError("E_INVALID_UTF8", "frame is not UTF-8");
        }

        var containsNonFinite = InspectStructure(utf8);
        try
        {
            var reader = new Utf8JsonReader(utf8, new JsonReaderOptions
            {
                AllowTrailingCommas = false,
                CommentHandling = JsonCommentHandling.Disallow,
                MaxDepth = NativeProtocolConstants.MaxParserDepth,
            });
            if (!reader.Read())
            {
                throw JsonFailure();
            }

            var value = ReadValue(ref reader, 0);
            if (reader.Read())
            {
                throw JsonFailure();
            }

            return value;
        }
        catch (NativeProtocolError)
        {
            throw;
        }
        catch (JsonException)
        {
            var code = containsNonFinite ? "E_NONFINITE_NUMBER" : "E_JSON";
            throw new NativeProtocolError(code, "frame body is not valid JSON");
        }
    }

    private static NativeJsonValue ReadValue(ref Utf8JsonReader reader, int depth)
    {
        if (depth > NativeProtocolConstants.MaxParserDepth)
        {
            throw new NativeProtocolError("E_JSON_DEPTH", "JSON exceeds maximum depth");
        }

        return reader.TokenType switch
        {
            JsonTokenType.Null => NativeJsonNull.Value,
            JsonTokenType.True => new NativeJsonBoolean(true),
            JsonTokenType.False => new NativeJsonBoolean(false),
            JsonTokenType.String => new NativeJsonString(ReadString(ref reader)),
            JsonTokenType.Number => ReadNumber(ref reader),
            JsonTokenType.StartArray => ReadArray(ref reader, depth),
            JsonTokenType.StartObject => ReadObject(ref reader, depth),
            _ => throw JsonFailure(),
        };
    }

    private static NativeJsonValue ReadNumber(ref Utf8JsonReader reader)
    {
        var raw = reader.ValueSpan;
        var isFloat = raw.Contains((byte)'.') || raw.Contains((byte)'e') || raw.Contains((byte)'E');
        if (!isFloat)
        {
            return reader.TryGetInt64(out var integer)
                ? new NativeJsonInteger(integer)
                : throw JsonFailure();
        }

        if (!reader.TryGetDouble(out var number) || !double.IsFinite(number))
        {
            throw new NativeProtocolError("E_NONFINITE_NUMBER", "JSON contains a non-finite number");
        }

        return new NativeJsonFloat(number);
    }

    private static NativeJsonArray ReadArray(ref Utf8JsonReader reader, int depth)
    {
        var values = new List<NativeJsonValue>();
        while (reader.Read() && reader.TokenType != JsonTokenType.EndArray)
        {
            values.Add(ReadValue(ref reader, depth + 1));
        }

        if (reader.TokenType != JsonTokenType.EndArray)
        {
            throw JsonFailure();
        }

        return new NativeJsonArray(values);
    }

    private static NativeJsonObject ReadObject(ref Utf8JsonReader reader, int depth)
    {
        var pairs = new List<KeyValuePair<string, NativeJsonValue>>();
        var keys = new HashSet<string>(StringComparer.Ordinal);
        while (reader.Read() && reader.TokenType != JsonTokenType.EndObject)
        {
            if (reader.TokenType != JsonTokenType.PropertyName)
            {
                throw JsonFailure();
            }

            var key = ReadString(ref reader);
            if (!keys.Add(key))
            {
                throw new NativeProtocolError("E_DUPLICATE_KEY", "JSON object contains a duplicate key");
            }

            if (!reader.Read())
            {
                throw JsonFailure();
            }

            pairs.Add(new KeyValuePair<string, NativeJsonValue>(key, ReadValue(ref reader, depth + 1)));
        }

        if (reader.TokenType != JsonTokenType.EndObject)
        {
            throw JsonFailure();
        }

        return new NativeJsonObject(pairs);
    }

    private static string ReadString(ref Utf8JsonReader reader)
    {
        ValidateUnicodeEscapes(reader.ValueSpan);
        var value = reader.GetString() ?? throw JsonFailure();
        for (var index = 0; index < value.Length; index++)
        {
            if (!char.IsSurrogate(value[index]))
            {
                continue;
            }

            if (!char.IsHighSurrogate(value[index]) || index + 1 >= value.Length || !char.IsLowSurrogate(value[++index]))
            {
                throw JsonFailure();
            }
        }

        return value;
    }

    private static void ValidateUnicodeEscapes(ReadOnlySpan<byte> raw)
    {
        for (var index = 0; index + 1 < raw.Length; index++)
        {
            if (raw[index] != (byte)'\\')
            {
                continue;
            }

            if (raw[++index] != (byte)'u' || index + 4 >= raw.Length)
            {
                continue;
            }

            var first = Hex4(raw[(index + 1)..]);
            index += 4;
            if (first is >= 0xd800 and <= 0xdbff)
            {
                if (index + 6 >= raw.Length || raw[index + 1] != (byte)'\\' || raw[index + 2] != (byte)'u'
                    || Hex4(raw[(index + 3)..]) is not (>= 0xdc00 and <= 0xdfff))
                {
                    throw JsonFailure();
                }

                index += 6;
            }
            else if (first is >= 0xdc00 and <= 0xdfff)
            {
                throw JsonFailure();
            }
        }
    }

    private static int Hex4(ReadOnlySpan<byte> raw)
    {
        if (raw.Length < 4)
        {
            throw JsonFailure();
        }

        var result = 0;
        for (var index = 0; index < 4; index++)
        {
            var digit = raw[index] switch
            {
                >= (byte)'0' and <= (byte)'9' => raw[index] - (byte)'0',
                >= (byte)'a' and <= (byte)'f' => raw[index] - (byte)'a' + 10,
                >= (byte)'A' and <= (byte)'F' => raw[index] - (byte)'A' + 10,
                _ => throw JsonFailure(),
            };
            result = (result << 4) | digit;
        }

        return result;
    }

    private static bool InspectStructure(ReadOnlySpan<byte> bytes)
    {
        var depth = 0;
        var inString = false;
        var escaped = false;
        var containsNonFinite = false;
        for (var index = 0; index < bytes.Length; index++)
        {
            var value = bytes[index];
            if (inString)
            {
                if (escaped)
                {
                    escaped = false;
                }
                else if (value == (byte)'\\')
                {
                    escaped = true;
                }
                else if (value == (byte)'"')
                {
                    inString = false;
                }
                continue;
            }

            inString = value == (byte)'"';
            if (value is (byte)'{' or (byte)'[' && ++depth > NativeProtocolConstants.MaxParserDepth)
            {
                throw new NativeProtocolError("E_JSON_DEPTH", "JSON exceeds maximum depth");
            }
            if (value is (byte)'}' or (byte)']')
            {
                depth--;
            }

            var remaining = bytes[index..];
            containsNonFinite |= !inString && (remaining.StartsWith("NaN"u8)
                || remaining.StartsWith("Infinity"u8) || remaining.StartsWith("-Infinity"u8));
        }

        return containsNonFinite;
    }

    private static NativeProtocolError JsonFailure() => new("E_JSON", "frame body is not valid JSON");
}
