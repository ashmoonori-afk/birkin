import Foundation

@testable import BirkinNativeProtocol

struct ProjectionEventVector {
    let cursor: Int
    let envelope: NativeEnvelope
    let expectedState: NativeJSONObject
}

struct ProjectionVectors {
    let snapshot: NativeEnvelope
    let snapshotExpectedState: NativeJSONObject
    let events: [ProjectionEventVector]
    let gapEvent: NativeEnvelope

    static func load() throws -> ProjectionVectors {
        guard let url = Bundle.module.url(
            forResource: "native-projection-vectors",
            withExtension: "json",
            subdirectory: "GoldenVectors"
        ) else {
            throw GoldenVectorError(description: "projection vector fixture is missing")
        }
        let data = try Data(contentsOf: url)
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let snapshot = root["snapshot"] as? [String: Any],
              let rawEvents = root["events"] as? [[String: Any]],
              let gap = root["gap_event"] as? [String: Any]
        else {
            throw GoldenVectorError(description: "projection vector fixture is malformed")
        }
        return ProjectionVectors(
            snapshot: try envelope(from: snapshot),
            snapshotExpectedState: try object(snapshot["expected_state"]),
            events: try rawEvents.map { raw in
                guard let cursor = raw["cursor"] as? Int else {
                    throw GoldenVectorError(description: "projection event cursor is missing")
                }
                return ProjectionEventVector(
                    cursor: cursor,
                    envelope: try envelope(from: raw),
                    expectedState: try object(raw["expected_state"])
                )
            },
            gapEvent: try envelope(from: gap)
        )
    }

    private static func envelope(from raw: [String: Any]) throws -> NativeEnvelope {
        guard let encoded = raw["frame_base64"] as? String,
              let frame = Data(base64Encoded: encoded)
        else {
            throw GoldenVectorError(description: "projection frame is malformed")
        }
        return try NativeEnvelope.decode(frame: frame)
    }

    private static func object(_ raw: Any?) throws -> NativeJSONObject {
        guard let raw else {
            throw GoldenVectorError(description: "expected projection state is missing")
        }
        let data = try JSONSerialization.data(withJSONObject: raw, options: [.sortedKeys])
        guard case .object(let object) = try NativeEnvelope.parseJSON(body: data) else {
            throw GoldenVectorError(description: "expected projection state is malformed")
        }
        return object
    }
}
