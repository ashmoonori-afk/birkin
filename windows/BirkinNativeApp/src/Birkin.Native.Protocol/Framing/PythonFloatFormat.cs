using System.Globalization;

namespace Birkin.Native.Protocol.Framing;

public static class PythonFloatFormat
{
    public static string Format(double value)
    {
        if (!double.IsFinite(value))
        {
            throw new NativeProtocolError("E_NONFINITE_NUMBER", "JSON contains a non-finite number");
        }

        var shortest = value.ToString("R", CultureInfo.InvariantCulture);
        var negative = shortest[0] == '-';
        var unsigned = negative ? shortest[1..] : shortest;
        var exponentMarker = unsigned.IndexOf('E', StringComparison.Ordinal);
        if (exponentMarker < 0)
        {
            exponentMarker = unsigned.IndexOf('e', StringComparison.Ordinal);
        }
        var mantissa = exponentMarker < 0 ? unsigned : unsigned[..exponentMarker];
        var exponent = exponentMarker < 0
            ? 0
            : int.Parse(unsigned[(exponentMarker + 1)..], NumberStyles.Integer, CultureInfo.InvariantCulture);
        var point = mantissa.IndexOf('.');
        var pointPosition = (point < 0 ? mantissa.Length : point) + exponent;
        var digits = mantissa.Replace(".", string.Empty, StringComparison.Ordinal);
        while (digits.Length > 1 && digits[0] == '0')
        {
            digits = digits[1..];
            pointPosition--;
        }

        if (digits == "0")
        {
            return negative ? "-0.0" : "0.0";
        }

        while (digits.Length > 1 && digits.EndsWith('0'))
        {
            digits = digits[..^1];
        }

        var sign = negative ? "-" : string.Empty;
        return pointPosition <= -4 || pointPosition > 16
            ? sign + Exponential(digits, pointPosition)
            : sign + Fixed(digits, pointPosition);
    }

    private static string Exponential(string digits, int pointPosition)
    {
        var exponent = pointPosition - 1;
        var mantissa = digits.Length == 1 ? digits : $"{digits[0]}.{digits[1..]}";
        return $"{mantissa}e{(exponent < 0 ? "-" : "+")}{Math.Abs(exponent).ToString("00", CultureInfo.InvariantCulture)}";
    }

    private static string Fixed(string digits, int pointPosition)
    {
        if (pointPosition <= 0)
        {
            return $"0.{new string('0', -pointPosition)}{digits}";
        }

        if (pointPosition >= digits.Length)
        {
            return $"{digits}{new string('0', pointPosition - digits.Length)}.0";
        }

        return $"{digits[..pointPosition]}.{digits[pointPosition..]}";
    }
}
