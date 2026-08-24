import Foundation

/// One golden vector produced by the real Python codec.
///
/// The fixture is regenerated with
/// `uv run python scripts/native/generate_golden_vectors.py`; nothing in the
/// Swift tree may hand-write these bytes.
struct GoldenVector: Sendable {
    let name: String
    let kind: String
    let frame: Data
    let frameByteCount: Int
}

struct GoldenVectorError: Error, CustomStringConvertible {
    let description: String
}

enum GoldenVectors {
    static let fixtureName = "native-protocol-vectors"

    static func all() throws -> [GoldenVector] {
        guard
            let url = Bundle.module.url(
                forResource: fixtureName,
                withExtension: "json",
                subdirectory: "GoldenVectors"
            )
        else {
            throw GoldenVectorError(description: "golden vector fixture is missing")
        }
        let document = try JSONSerialization.jsonObject(with: Data(contentsOf: url))
        guard
            let root = document as? [String: Any],
            let rawVectors = root["vectors"] as? [[String: Any]]
        else {
            throw GoldenVectorError(description: "golden vector fixture is malformed")
        }
        return try rawVectors.map { raw in
            guard
                let name = raw["name"] as? String,
                let kind = raw["kind"] as? String,
                let encoded = raw["frame_base64"] as? String,
                let frame = Data(base64Encoded: encoded),
                let byteCount = raw["frame_byte_count"] as? Int
            else {
                throw GoldenVectorError(description: "golden vector entry is malformed")
            }
            return GoldenVector(
                name: name,
                kind: kind,
                frame: frame,
                frameByteCount: byteCount
            )
        }
    }

    static func named(_ name: String) throws -> GoldenVector {
        guard let vector = try all().first(where: { $0.name == name }) else {
            throw GoldenVectorError(description: "golden vector \(name) is missing")
        }
        return vector
    }

    /// The protocol constants the Python codec reported when generating.
    static func protocolConstants() throws -> [String: Any] {
        guard
            let url = Bundle.module.url(
                forResource: fixtureName,
                withExtension: "json",
                subdirectory: "GoldenVectors"
            ),
            let root = try JSONSerialization.jsonObject(with: Data(contentsOf: url))
                as? [String: Any],
            let constants = root["protocol"] as? [String: Any]
        else {
            throw GoldenVectorError(description: "golden vector constants are missing")
        }
        return constants
    }
}
