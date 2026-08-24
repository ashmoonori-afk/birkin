/// String scanning for `NativeJSONParser`.
///
/// JSON escapes are decoded exactly as Python's strict decoder does, with one
/// documented narrowing: Python tolerates a lone `\uD800`-range surrogate,
/// which a Swift `String` cannot represent, so it is refused as invalid JSON.
extension NativeJSONParser {
    mutating func parseString() throws(NativeProtocolError) -> String {
        index += 1
        var scalars = String.UnicodeScalarView()
        while true {
            guard index < bytes.count else {
                throw Self.failure(.json, "frame body is not valid JSON")
            }
            let byte = bytes[index]
            if byte == UInt8(ascii: "\"") {
                index += 1
                return String(scalars)
            }
            if byte < 0x20 {
                throw Self.failure(.json, "frame body is not valid JSON")
            }
            if byte == UInt8(ascii: "\\") {
                index += 1
                scalars.append(try parseEscape())
                continue
            }
            let start = index
            while index < bytes.count,
                bytes[index] != UInt8(ascii: "\""),
                bytes[index] != UInt8(ascii: "\\"),
                bytes[index] >= 0x20
            {
                index += 1
            }
            scalars.append(contentsOf: String(decoding: bytes[start..<index], as: UTF8.self).unicodeScalars)
        }
    }

    mutating func parseEscape() throws(NativeProtocolError) -> Unicode.Scalar {
        guard index < bytes.count else {
            throw Self.failure(.json, "frame body is not valid JSON")
        }
        let byte = bytes[index]
        index += 1
        switch byte {
        case UInt8(ascii: "\""): return Unicode.Scalar(0x22)!
        case UInt8(ascii: "\\"): return Unicode.Scalar(0x5C)!
        case UInt8(ascii: "/"): return Unicode.Scalar(0x2F)!
        case UInt8(ascii: "b"): return Unicode.Scalar(0x08)!
        case UInt8(ascii: "f"): return Unicode.Scalar(0x0C)!
        case UInt8(ascii: "n"): return Unicode.Scalar(0x0A)!
        case UInt8(ascii: "r"): return Unicode.Scalar(0x0D)!
        case UInt8(ascii: "t"): return Unicode.Scalar(0x09)!
        case UInt8(ascii: "u"): return try parseUnicodeEscape()
        default: throw Self.failure(.json, "frame body is not valid JSON")
        }
    }

    /// Decode `\uXXXX`, joining surrogate pairs. Python's decoder tolerates a
    /// lone surrogate; Swift strings cannot hold one, so it is refused here.
    mutating func parseUnicodeEscape() throws(NativeProtocolError) -> Unicode.Scalar {
        let first = try parseHex4()
        if first >= 0xD800, first <= 0xDBFF {
            guard index + 1 < bytes.count,
                bytes[index] == UInt8(ascii: "\\"),
                bytes[index + 1] == UInt8(ascii: "u")
            else {
                throw Self.failure(.json, "frame body is not valid JSON")
            }
            index += 2
            let second = try parseHex4()
            guard second >= 0xDC00, second <= 0xDFFF else {
                throw Self.failure(.json, "frame body is not valid JSON")
            }
            let combined = 0x10000 + ((first - 0xD800) << 10) + (second - 0xDC00)
            guard let scalar = Unicode.Scalar(combined) else {
                throw Self.failure(.json, "frame body is not valid JSON")
            }
            return scalar
        }
        guard let scalar = Unicode.Scalar(first) else {
            throw Self.failure(.json, "frame body is not valid JSON")
        }
        return scalar
    }

    mutating func parseHex4() throws(NativeProtocolError) -> UInt32 {
        var value: UInt32 = 0
        for _ in 0..<4 {
            guard index < bytes.count, let digit = Self.hexDigit(bytes[index]) else {
                throw Self.failure(.json, "frame body is not valid JSON")
            }
            value = value << 4 | digit
            index += 1
        }
        return value
    }

    static func hexDigit(_ byte: UInt8) -> UInt32? {
        switch byte {
        case UInt8(ascii: "0")...UInt8(ascii: "9"): return UInt32(byte - UInt8(ascii: "0"))
        case UInt8(ascii: "a")...UInt8(ascii: "f"): return UInt32(byte - UInt8(ascii: "a") + 10)
        case UInt8(ascii: "A")...UInt8(ascii: "F"): return UInt32(byte - UInt8(ascii: "A") + 10)
        default: return nil
        }
    }
}
