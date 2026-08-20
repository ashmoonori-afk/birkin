/// A strict JSON reader matching Python's `json` module as the bridge uses it.
///
/// Differences from a permissive reader, each mirroring the Python codec:
/// duplicate object keys are refused, the non-finite literals Python's decoder
/// would accept (`NaN`, `Infinity`, `-Infinity`) are refused, unescaped control
/// characters are refused, and trailing content after the top-level value is
/// refused.
struct NativeJSONParser {
    /// A recursion guard. Python's decoder relies on its own recursion limit;
    /// the envelope body is separately bounded by `NativeProtocol.maxJSONDepth`.
    static let maxParseDepth = 128

    let bytes: [UInt8]
    var index: Int

    private init(bytes: [UInt8]) {
        self.bytes = bytes
        index = 0
    }

    /// Parse one complete JSON document from validated UTF-8 bytes.
    static func parse(utf8 bytes: [UInt8]) throws(NativeProtocolError) -> NativeJSONValue {
        var parser = NativeJSONParser(bytes: bytes)
        parser.skipWhitespace()
        let value = try parser.parseValue(depth: 0)
        parser.skipWhitespace()
        guard parser.index == parser.bytes.count else {
            throw Self.failure(.json, "frame body is not valid JSON")
        }
        return value
    }

    static func failure(
        _ code: NativeProtocolError.Code,
        _ message: String
    ) -> NativeProtocolError {
        NativeProtocolError(code, message)
    }

    private mutating func skipWhitespace() {
        while index < bytes.count {
            switch bytes[index] {
            case 0x20, 0x09, 0x0A, 0x0D: index += 1
            default: return
            }
        }
    }

    func peek() -> UInt8? { index < bytes.count ? bytes[index] : nil }

    private mutating func parseValue(depth: Int) throws(NativeProtocolError) -> NativeJSONValue {
        guard depth <= Self.maxParseDepth else {
            throw Self.failure(.jsonDepth, "JSON exceeds maximum depth")
        }
        guard let byte = peek() else {
            throw Self.failure(.json, "frame body is not valid JSON")
        }
        switch byte {
        case UInt8(ascii: "{"): return .object(try parseObject(depth: depth))
        case UInt8(ascii: "["): return .array(try parseArray(depth: depth))
        case UInt8(ascii: "\""): return .string(try parseString())
        case UInt8(ascii: "t"):
            try expect(literal: "true")
            return .bool(true)
        case UInt8(ascii: "f"):
            try expect(literal: "false")
            return .bool(false)
        case UInt8(ascii: "n"):
            try expect(literal: "null")
            return .null
        case UInt8(ascii: "N"), UInt8(ascii: "I"):
            throw Self.failure(.nonfiniteNumber, "JSON contains a non-finite number")
        default: return try parseNumber()
        }
    }

    private mutating func expect(literal: String) throws(NativeProtocolError) {
        for scalar in literal.utf8 {
            guard index < bytes.count, bytes[index] == scalar else {
                throw Self.failure(.json, "frame body is not valid JSON")
            }
            index += 1
        }
    }

    private mutating func parseObject(depth: Int) throws(NativeProtocolError) -> NativeJSONObject {
        index += 1
        var object = NativeJSONObject()
        skipWhitespace()
        if peek() == UInt8(ascii: "}") {
            index += 1
            return object
        }
        while true {
            skipWhitespace()
            guard peek() == UInt8(ascii: "\"") else {
                throw Self.failure(.json, "frame body is not valid JSON")
            }
            let key = try parseString()
            skipWhitespace()
            guard peek() == UInt8(ascii: ":") else {
                throw Self.failure(.json, "frame body is not valid JSON")
            }
            index += 1
            skipWhitespace()
            try object.append(key: key, value: try parseValue(depth: depth + 1))
            skipWhitespace()
            switch peek() {
            case UInt8(ascii: ","): index += 1
            case UInt8(ascii: "}"):
                index += 1
                return object
            default: throw Self.failure(.json, "frame body is not valid JSON")
            }
        }
    }

    private mutating func parseArray(depth: Int) throws(NativeProtocolError) -> [NativeJSONValue] {
        index += 1
        var values: [NativeJSONValue] = []
        skipWhitespace()
        if peek() == UInt8(ascii: "]") {
            index += 1
            return values
        }
        while true {
            skipWhitespace()
            values.append(try parseValue(depth: depth + 1))
            skipWhitespace()
            switch peek() {
            case UInt8(ascii: ","): index += 1
            case UInt8(ascii: "]"):
                index += 1
                return values
            default: throw Self.failure(.json, "frame body is not valid JSON")
            }
        }
    }

    /// Scan a number exactly as Python's `json` NUMBER_RE allows: no leading
    /// plus, no leading zeros, no bare `.5`, no trailing `5.`.
    private mutating func parseNumber() throws(NativeProtocolError) -> NativeJSONValue {
        let start = index
        if peek() == UInt8(ascii: "-") {
            index += 1
            if peek() == UInt8(ascii: "I") {
                throw Self.failure(.nonfiniteNumber, "JSON contains a non-finite number")
            }
        }
        guard let leading = peek(), Self.isDigit(leading) else {
            throw Self.failure(.json, "frame body is not valid JSON")
        }
        if leading == UInt8(ascii: "0") {
            index += 1
        } else {
            while let byte = peek(), Self.isDigit(byte) { index += 1 }
        }
        var isInteger = true
        if peek() == UInt8(ascii: ".") {
            isInteger = false
            index += 1
            try requireDigits()
        }
        if let byte = peek(), byte == UInt8(ascii: "e") || byte == UInt8(ascii: "E") {
            isInteger = false
            index += 1
            if let sign = peek(), sign == UInt8(ascii: "+") || sign == UInt8(ascii: "-") {
                index += 1
            }
            try requireDigits()
        }
        let text = String(decoding: bytes[start..<index], as: UTF8.self)
        if isInteger {
            guard let value = Int(text) else {
                throw Self.failure(.json, "integer is outside the supported range")
            }
            return .int(value)
        }
        guard let value = Double(text) else {
            throw Self.failure(.json, "frame body is not valid JSON")
        }
        guard value.isFinite else {
            throw Self.failure(.nonfiniteNumber, "JSON contains a non-finite number")
        }
        return .double(value)
    }

    private mutating func requireDigits() throws(NativeProtocolError) {
        guard let byte = peek(), Self.isDigit(byte) else {
            throw Self.failure(.json, "frame body is not valid JSON")
        }
        while let byte = peek(), Self.isDigit(byte) { index += 1 }
    }

    private static func isDigit(_ byte: UInt8) -> Bool {
        byte >= UInt8(ascii: "0") && byte <= UInt8(ascii: "9")
    }
}
