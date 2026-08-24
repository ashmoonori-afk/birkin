using System.Globalization;
using System.Text;

namespace Birkin.Native.Protocol.Framing;

public static class NativeJsonSerializer
{
    public static byte[] Serialize(NativeJsonValue value)
    {
        var json = new StringBuilder();
        Write(value, json);
        try
        {
            return new UTF8Encoding(false, true).GetBytes(json.ToString());
        }
        catch (EncoderFallbackException)
        {
            throw new NativeProtocolError("E_JSON", "frame contains an invalid Unicode string");
        }
    }

    private static void Write(NativeJsonValue value, StringBuilder json)
    {
        switch (value)
        {
            case NativeJsonNull:
                _ = json.Append("null");
                break;
            case NativeJsonBoolean boolean:
                _ = json.Append(boolean.Value ? "true" : "false");
                break;
            case NativeJsonInteger integer:
                _ = json.Append(integer.Value.ToString(CultureInfo.InvariantCulture));
                break;
            case NativeJsonFloat number:
                _ = json.Append(PythonFloatFormat.Format(number.Value));
                break;
            case NativeJsonString text:
                WriteString(text.Value, json);
                break;
            case NativeJsonArray array:
                WriteArray(array, json);
                break;
            case NativeJsonObject obj:
                WriteObject(obj, json);
                break;
            default:
                throw new NativeProtocolError("E_JSON", "body contains a non-JSON value");
        }
    }

    private static void WriteArray(NativeJsonArray array, StringBuilder json)
    {
        _ = json.Append('[');
        for (var index = 0; index < array.Values.Count; index++)
        {
            if (index != 0)
            {
                _ = json.Append(',');
            }

            Write(array.Values[index], json);
        }

        _ = json.Append(']');
    }

    private static void WriteObject(NativeJsonObject obj, StringBuilder json)
    {
        _ = json.Append('{');
        for (var index = 0; index < obj.Pairs.Count; index++)
        {
            if (index != 0)
            {
                _ = json.Append(',');
            }

            WriteString(obj.Pairs[index].Key, json);
            _ = json.Append(':');
            Write(obj.Pairs[index].Value, json);
        }

        _ = json.Append('}');
    }

    private static void WriteString(string value, StringBuilder json)
    {
        _ = json.Append('"');
        for (var index = 0; index < value.Length; index++)
        {
            var character = value[index];
            switch (character)
            {
                case '"': _ = json.Append("\\\""); break;
                case '\\': _ = json.Append("\\\\"); break;
                case '\b': _ = json.Append("\\b"); break;
                case '\f': _ = json.Append("\\f"); break;
                case '\n': _ = json.Append("\\n"); break;
                case '\r': _ = json.Append("\\r"); break;
                case '\t': _ = json.Append("\\t"); break;
                default:
                    if (character < 0x20)
                    {
                        _ = json.Append("\\u").Append(((int)character).ToString("x4", CultureInfo.InvariantCulture));
                    }
                    else if (char.IsHighSurrogate(character) && index + 1 < value.Length && char.IsLowSurrogate(value[index + 1]))
                    {
                        _ = json.Append(character).Append(value[++index]);
                    }
                    else if (char.IsSurrogate(character))
                    {
                        throw new NativeProtocolError("E_JSON", "JSON contains an unpaired surrogate");
                    }
                    else
                    {
                        _ = json.Append(character);
                    }
                    break;
            }
        }

        _ = json.Append('"');
    }
}
