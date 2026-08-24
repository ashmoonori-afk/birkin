using System.Globalization;
using Birkin.Native.Protocol.Framing;

namespace Birkin.Native.Protocol.Messaging;

public static class NativeProtocolDate
{
    public static DateTimeOffset Parse(string value, string code)
    {
        var timezoneStart = Math.Max(value.LastIndexOf('+'), value.LastIndexOf('-'));
        var timezoneAware = value.EndsWith('Z')
            || timezoneStart > value.IndexOf('T')
                && value.Length - timezoneStart == 6
                && value[^3] == ':';
        if (!timezoneAware || !string.Equals(value, value.Trim(), StringComparison.Ordinal)
            || !DateTimeOffset.TryParse(
            value,
            CultureInfo.InvariantCulture,
            DateTimeStyles.AllowLeadingWhite | DateTimeStyles.AllowTrailingWhite,
            out var parsed))
        {
            throw new NativeProtocolError(code, "protocol date must be an ISO-8601 timestamp with timezone");
        }

        return parsed;
    }
}
