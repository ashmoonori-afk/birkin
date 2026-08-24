/// One JSON value carried by a native envelope body.
///
/// Integers and doubles stay distinct because the Python codec re-encodes them
/// distinctly (`1` and `1.0` are different bytes on the wire).
public indirect enum NativeJSONValue: Equatable, Sendable {
    case null
    case bool(Bool)
    case int(Int)
    case double(Double)
    case string(String)
    case array([NativeJSONValue])
    case object(NativeJSONObject)
}

/// A JSON object that remembers the order its keys arrived in.
///
/// Key order is meaningless to JSON equality, so `==` ignores it, but the
/// Python codec serialises a body in insertion order. Preserving that order is
/// what lets Swift re-encode a decoded frame to byte-identical bytes.
public struct NativeJSONObject: Equatable, Sendable, ExpressibleByDictionaryLiteral {
    private var order: [String]
    private var storage: [String: NativeJSONValue]

    public init() {
        order = []
        storage = [:]
    }

    public init(dictionaryLiteral elements: (String, NativeJSONValue)...) {
        self.init()
        for (key, value) in elements {
            set(key, to: value)
        }
    }

    /// The keys in the order they were inserted.
    public var keys: [String] { order }

    public var count: Int { order.count }

    public var isEmpty: Bool { order.isEmpty }

    public subscript(key: String) -> NativeJSONValue? { storage[key] }

    /// The key/value pairs in insertion order.
    public var pairs: [(key: String, value: NativeJSONValue)] {
        order.map { ($0, storage[$0]!) }
    }

    /// Append a key that must not already exist; duplicates are a refusal on
    /// the wire, exactly as the Python decoder treats them.
    public mutating func append(
        key: String,
        value: NativeJSONValue
    ) throws(NativeProtocolError) {
        guard storage[key] == nil else {
            throw NativeProtocolError(
                .duplicateKey,
                "JSON object contains a duplicate key"
            )
        }
        order.append(key)
        storage[key] = value
    }

    private mutating func set(_ key: String, to value: NativeJSONValue) {
        if storage[key] == nil {
            order.append(key)
        }
        storage[key] = value
    }

    public static func == (lhs: NativeJSONObject, rhs: NativeJSONObject) -> Bool {
        lhs.storage == rhs.storage
    }
}
