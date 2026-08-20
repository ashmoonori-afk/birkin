/// Renders a `Double` the way CPython's `repr` does, which is what
/// `json.dumps` writes for floats.
///
/// Both languages emit the shortest decimal digits that round-trip, so the
/// digits agree; only the layout rules differ. CPython switches to exponent
/// form when the decimal point sits at or before position -4, or beyond
/// position 16, and always keeps a `.0` on an otherwise integral value.
enum PythonFloatFormat {
    static func repr(_ value: Double) -> String {
        let shortest = value.description
        let negative = shortest.hasPrefix("-")
        let unsigned = negative ? String(shortest.dropFirst()) : shortest
        guard var (digits, pointPosition) = decompose(unsigned), !digits.isEmpty else {
            return shortest
        }
        while digits.count > 1, digits.first == "0" {
            digits.removeFirst()
            pointPosition -= 1
        }
        while digits.count > 1, digits.last == "0" {
            digits.removeLast()
        }
        if digits == "0" { return negative ? "-0.0" : "0.0" }
        let sign = negative ? "-" : ""
        if pointPosition <= -4 || pointPosition > 16 {
            return sign + exponential(digits: digits, pointPosition: pointPosition)
        }
        return sign + fixed(digits: digits, pointPosition: pointPosition)
    }

    /// Split `123.45` or `1.2e+17` into significant digits and the position of
    /// the decimal point, so that the value is `0.<digits> * 10^position`.
    private static func decompose(_ text: String) -> (String, Int)? {
        let parts = text.split(separator: "e", omittingEmptySubsequences: false)
        guard parts.count <= 2, let mantissa = parts.first else { return nil }
        var exponent = 0
        if parts.count == 2 {
            guard let parsed = Int(parts[1]) else { return nil }
            exponent = parsed
        }
        let halves = mantissa.split(separator: ".", omittingEmptySubsequences: false)
        guard let integerPart = halves.first, halves.count <= 2 else { return nil }
        let fraction = halves.count == 2 ? String(halves[1]) : ""
        guard integerPart.allSatisfy(\.isNumber), fraction.allSatisfy(\.isNumber) else {
            return nil
        }
        return (String(integerPart) + fraction, integerPart.count + exponent)
    }

    private static func exponential(digits: String, pointPosition: Int) -> String {
        let lead = String(digits.first!)
        let rest = String(digits.dropFirst())
        let exponent = pointPosition - 1
        let magnitude = abs(exponent)
        let padded = magnitude < 10 ? "0\(magnitude)" : "\(magnitude)"
        let mantissa = rest.isEmpty ? lead : "\(lead).\(rest)"
        return "\(mantissa)e\(exponent < 0 ? "-" : "+")\(padded)"
    }

    private static func fixed(digits: String, pointPosition: Int) -> String {
        if pointPosition <= 0 {
            return "0." + String(repeating: "0", count: -pointPosition) + digits
        }
        if pointPosition >= digits.count {
            let padding = String(repeating: "0", count: pointPosition - digits.count)
            return digits + padding + ".0"
        }
        let split = digits.index(digits.startIndex, offsetBy: pointPosition)
        return String(digits[..<split]) + "." + String(digits[split...])
    }
}
