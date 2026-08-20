/// Ephemeral, in-memory ownership of the latest canonical Python projection.
/// This type deliberately has no persistence dependency or serialization API.
public final class NativeProjectionStore {
    public private(set) var projection: NativeProjectionState?

    public init() {}

    public var latestAppliedCursor: Int? { projection?.cursor }

    public func apply(snapshot envelope: NativeEnvelope) throws {
        guard envelope.kind == .snapshot else {
            throw NativeProjectionError("projection snapshot requires a snapshot envelope")
        }
        projection = try Self.decodeSnapshot(envelope.body)
    }

    private static func decodeSnapshot(
        _ body: NativeJSONObject
    ) throws -> NativeProjectionState {
        let expectedKeys: Set<String> = [
            "protocol_version", "session_id", "cursor", "panels", "conversation",
            "composer", "status", "instance_id", "reset_reason",
        ]
        guard Set(body.keys) == expectedKeys else {
            throw NativeProjectionError("projection snapshot keys do not match the contract")
        }
        let panels = try objectArray(body["panels"], label: "panels").map { panel in
            guard Set(panel.keys) == ["key", "items"] else {
                throw NativeProjectionError("projection panel keys do not match the contract")
            }
            return NativeProjectionPanel(
                key: try string(panel["key"], label: "panel key"),
                items: try objectArray(panel["items"], label: "panel items")
            )
        }
        let composer = try object(body["composer"], label: "composer")
        guard Set(composer.keys) == ["can_send", "can_interrupt", "can_resume"] else {
            throw NativeProjectionError("projection composer keys do not match the contract")
        }
        let status = try object(body["status"], label: "status")
        guard Set(status.keys) == ["connection"] else {
            throw NativeProjectionError("projection status keys do not match the contract")
        }
        return NativeProjectionState(
            protocolVersion: try integer(body["protocol_version"], label: "protocol_version"),
            sessionID: try string(body["session_id"], label: "session_id"),
            cursor: try integer(body["cursor"], label: "cursor"),
            panels: panels,
            conversation: try objectArray(body["conversation"], label: "conversation"),
            composer: NativeProjectionComposer(
                canSend: try boolean(composer["can_send"], label: "can_send"),
                canInterrupt: try boolean(composer["can_interrupt"], label: "can_interrupt"),
                canResume: try boolean(composer["can_resume"], label: "can_resume")
            ),
            connection: try string(status["connection"], label: "connection")
        )
    }

    static func object(
        _ value: NativeJSONValue?,
        label: String
    ) throws -> NativeJSONObject {
        guard case .object(let object) = value else {
            throw NativeProjectionError("\(label) must be an object")
        }
        return object
    }

    static func objectArray(
        _ value: NativeJSONValue?,
        label: String
    ) throws -> [NativeJSONObject] {
        guard case .array(let values) = value else {
            throw NativeProjectionError("\(label) must be an array")
        }
        return try values.map { try object($0, label: "\(label) item") }
    }

    static func string(_ value: NativeJSONValue?, label: String) throws -> String {
        guard case .string(let text) = value else {
            throw NativeProjectionError("\(label) must be a string")
        }
        return text
    }

    static func integer(_ value: NativeJSONValue?, label: String) throws -> Int {
        guard case .int(let number) = value, number >= 0 else {
            throw NativeProjectionError("\(label) must be a non-negative integer")
        }
        return number
    }

    static func boolean(_ value: NativeJSONValue?, label: String) throws -> Bool {
        guard case .bool(let flag) = value else {
            throw NativeProjectionError("\(label) must be a boolean")
        }
        return flag
    }
}
