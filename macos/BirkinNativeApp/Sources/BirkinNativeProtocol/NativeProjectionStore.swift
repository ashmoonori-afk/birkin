/// Ephemeral, in-memory ownership of the latest canonical Python projection.
/// This type deliberately has no persistence dependency or serialization API.
public final class NativeProjectionStore {
    public private(set) var projection: NativeProjectionState?
    public private(set) var status: NativeProjectionStoreStatus = .empty
    private var activeCommands: Set<String> = []
    private var interrupted = false

    public init() {}

    public var latestAppliedCursor: Int? { projection?.cursor }

    public func apply(snapshot envelope: NativeEnvelope) throws {
        guard envelope.kind == .snapshot else {
            throw NativeProjectionError("projection snapshot requires a snapshot envelope")
        }
        let decoded = try Self.decodeSnapshot(envelope.body)
        projection = decoded
        status = .current
        activeCommands = decoded.composer.canInterrupt ? ["__snapshot_active__"] : []
        interrupted = decoded.composer.canResume
    }

    public func apply(event envelope: NativeEnvelope) throws {
        guard envelope.kind == .event else {
            throw NativeProjectionError("projection event requires an event envelope")
        }
        let event = try Self.decodeEvent(envelope.body)
        guard var current = projection else {
            throw NativeProjectionError("projection event requires a snapshot")
        }
        guard event.protocolVersion == current.protocolVersion,
              event.sessionID == current.sessionID else {
            throw NativeProjectionError("projection event identity does not match the snapshot")
        }
        guard event.cursor > current.cursor else {
            throw NativeProjectionError("projection event cursor is not increasing")
        }
        guard event.cursor == current.cursor + 1 else {
            projection = nil
            activeCommands = []
            interrupted = false
            status = .replayRequired(NativeReplayRequest(
                afterCursor: 0,
                knownInstanceID: nil,
                replay: true
            ))
            return
        }
        NativeProjectionReducer.reduce(
            &current,
            event: event,
            activeCommands: &activeCommands,
            interrupted: &interrupted
        )
        projection = current
    }

    private static func decodeEvent(_ body: NativeJSONObject) throws -> NativeProjectionEvent {
        let expectedKeys: Set<String> = [
            "protocol_version", "session_id", "cursor", "event_id", "type",
            "timestamp", "actor_id", "command_id", "payload",
        ]
        guard Set(body.keys) == expectedKeys else {
            throw NativeProjectionError("projection event keys do not match the contract")
        }
        _ = try string(body["timestamp"], label: "timestamp")
        return NativeProjectionEvent(
            protocolVersion: try integer(body["protocol_version"], label: "protocol_version"),
            sessionID: try string(body["session_id"], label: "session_id"),
            cursor: try integer(body["cursor"], label: "cursor"),
            eventID: try string(body["event_id"], label: "event_id"),
            type: try string(body["type"], label: "type"),
            actorID: try string(body["actor_id"], label: "actor_id"),
            commandID: try string(body["command_id"], label: "command_id"),
            payload: try object(body["payload"], label: "payload")
        )
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
