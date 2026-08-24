/// Writes JSON exactly the way the Python bridge writes it.
///
/// The bridge calls `json.dumps(..., ensure_ascii=False, separators=(",", ":"))`,
/// so: no whitespace, non-ASCII text left as UTF-8, only `"`, `\` and the
/// C0 controls escaped, and object keys emitted in insertion order. Matching
/// this byte for byte is what lets a decoded frame be re-encoded identically.
enum NativeJSONSerializer {
    static func encode(object: NativeJSONObject) -> [UInt8] {
        var bytes: [UInt8] = []
        write(.object(object), into: &bytes)
        return bytes
    }

    static func encode(value: NativeJSONValue) -> [UInt8] {
        var bytes: [UInt8] = []
        write(value, into: &bytes)
        return bytes
    }

    private static func write(_ value: NativeJSONValue, into bytes: inout [UInt8]) {
        switch value {
        case .null:
            bytes.append(contentsOf: "null".utf8)
        case .bool(let flag):
            bytes.append(contentsOf: (flag ? "true" : "false").utf8)
        case .int(let number):
            bytes.append(contentsOf: String(number).utf8)
        case .double(let number):
            bytes.append(contentsOf: PythonFloatFormat.repr(number).utf8)
        case .string(let text):
            write(string: text, into: &bytes)
        case .array(let values):
            bytes.append(UInt8(ascii: "["))
            for (offset, element) in values.enumerated() {
                if offset > 0 { bytes.append(UInt8(ascii: ",")) }
                write(element, into: &bytes)
            }
            bytes.append(UInt8(ascii: "]"))
        case .object(let object):
            bytes.append(UInt8(ascii: "{"))
            for (offset, pair) in object.pairs.enumerated() {
                if offset > 0 { bytes.append(UInt8(ascii: ",")) }
                write(string: pair.key, into: &bytes)
                bytes.append(UInt8(ascii: ":"))
                write(pair.value, into: &bytes)
            }
            bytes.append(UInt8(ascii: "}"))
        }
    }

    private static func write(string text: String, into bytes: inout [UInt8]) {
        bytes.append(UInt8(ascii: "\""))
        for scalar in text.unicodeScalars {
            switch scalar {
            case "\"": bytes.append(contentsOf: "\\\"".utf8)
            case "\\": bytes.append(contentsOf: "\\\\".utf8)
            case "\u{08}": bytes.append(contentsOf: "\\b".utf8)
            case "\u{0C}": bytes.append(contentsOf: "\\f".utf8)
            case "\n": bytes.append(contentsOf: "\\n".utf8)
            case "\r": bytes.append(contentsOf: "\\r".utf8)
            case "\t": bytes.append(contentsOf: "\\t".utf8)
            default:
                if scalar.value < 0x20 {
                    let hex = String(scalar.value, radix: 16)
                    let padding = String(repeating: "0", count: 4 - hex.count)
                    bytes.append(contentsOf: "\\u\(padding)\(hex)".utf8)
                } else {
                    bytes.append(contentsOf: String(scalar).utf8)
                }
            }
        }
        bytes.append(UInt8(ascii: "\""))
    }
}
