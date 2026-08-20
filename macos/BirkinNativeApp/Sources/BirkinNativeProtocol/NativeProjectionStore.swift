/// Ephemeral, in-memory ownership of the latest canonical Python projection.
/// This type deliberately has no persistence dependency or serialization API.
public final class NativeProjectionStore {
    public private(set) var projection: NativeProjectionState?
    public private(set) var status: NativeProjectionStoreStatus = .empty
    public private(set) var requestedSurfaceRevisions: [String: Int] = [:]
    private var surfaces: [String: NativeSurfaceProjection] = [:]
    private var activeCommands: Set<String> = []
    private var interrupted = false

    public init() {}

    public var latestAppliedCursor: Int? { projection?.cursor }

    public func surface(named name: String) -> NativeSurfaceProjection? {
        surfaces[name]
    }

    public func apply(surface envelope: NativeEnvelope) throws {
        guard envelope.kind == .surfaceSnapshot || envelope.kind == .surfaceEvent else {
            throw NativeProjectionError("surface projection requires a surface envelope")
        }
        guard Set(envelope.body.keys) == ["surface", "revision", "payload"] else {
            throw NativeProjectionError("surface projection keys do not match the contract")
        }
        let name = try Self.string(envelope.body["surface"], label: "surface")
        let revision = try Self.integer(envelope.body["revision"], label: "surface revision")
        let payload = try Self.object(envelope.body["payload"], label: "surface payload")
        if envelope.kind == .surfaceEvent {
            guard let current = surfaces[name], revision == current.revision + 1 else {
                surfaces[name] = nil
                requestedSurfaceRevisions[name] = 0
                status = .replayRequired(NativeReplayRequest(
                    afterCursor: 0,
                    knownInstanceID: nil,
                    replay: true
                ))
                return
            }
        }
        surfaces[name] = NativeSurfaceProjection(
            name: name, revision: revision, payload: payload
        )
        requestedSurfaceRevisions[name] = revision
    }

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
            "composer", "status", "working_memory", "approval_policy", "terminals",
            "instance_id", "reset_reason",
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
        let workingMemory = try decodeWorkingMemory(
            try object(body["working_memory"], label: "working_memory")
        )
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
            connection: try string(status["connection"], label: "connection"),
            workingMemory: workingMemory,
            approvalPolicy: try object(body["approval_policy"], label: "approval_policy"),
            terminals: try objectArray(body["terminals"], label: "terminals").map(
                decodeTerminal
            )
        )
    }

    private static func decodeTerminal(
        _ value: NativeJSONObject
    ) throws -> NativeTerminalProjection {
        let keys: Set<String> = [
            "terminal_id", "cwd", "screen", "output_sequence", "state",
            "exit_status", "columns", "rows", "lease", "read_only",
        ]
        guard Set(value.keys) == keys else {
            throw NativeProjectionError("terminal projection keys do not match the contract")
        }
        let exitStatus: Int?
        switch value["exit_status"] {
        case .int(let value): exitStatus = value
        case .null: exitStatus = nil
        default: throw NativeProjectionError("terminal exit_status must be an integer or null")
        }
        let lease: String?
        switch value["lease"] {
        case .string(let value): lease = value
        case .null: lease = nil
        default: throw NativeProjectionError("terminal lease must be a string or null")
        }
        return NativeTerminalProjection(
            terminalID: try string(value["terminal_id"], label: "terminal_id"),
            cwd: try string(value["cwd"], label: "terminal cwd"),
            screen: try string(value["screen"], label: "terminal screen"),
            outputSequence: try integer(value["output_sequence"], label: "output_sequence"),
            state: try string(value["state"], label: "terminal state"),
            exitStatus: exitStatus,
            columns: try integer(value["columns"], label: "terminal columns"),
            rows: try integer(value["rows"], label: "terminal rows"),
            lease: lease,
            readOnly: try boolean(value["read_only"], label: "terminal read_only")
        )
    }

    private static func decodeWorkingMemory(
        _ value: NativeJSONObject
    ) throws -> NativeWorkingMemoryProjection {
        guard Set(value.keys) == ["revision", "goal", "fields", "files_evidence"] else {
            throw NativeProjectionError("working_memory keys do not match the contract")
        }
        let fieldsObject = try object(value["fields"], label: "working_memory fields")
        let requiredFields: Set<String> = [
            "corrections", "constraints", "decisions", "incomplete", "evidence",
            "next_actions",
        ]
        guard Set(fieldsObject.keys) == requiredFields else {
            throw NativeProjectionError("working_memory fields do not match the contract")
        }
        var fields: [String: [String]] = [:]
        for key in requiredFields {
            fields[key] = try stringArray(fieldsObject[key], label: key)
        }
        var goal: NativeWorkingMemoryGoal?
        if value["goal"] != .null {
            let object = try object(value["goal"], label: "working_memory goal")
            guard Set(object.keys) == ["slug", "objective", "tokens_used", "status"] else {
                throw NativeProjectionError("working_memory goal keys do not match the contract")
            }
            goal = NativeWorkingMemoryGoal(
                slug: try string(object["slug"], label: "goal slug"),
                objective: try string(object["objective"], label: "goal objective"),
                tokensUsed: try integer(object["tokens_used"], label: "goal tokens_used"),
                status: try string(object["status"], label: "goal status")
            )
        }
        return NativeWorkingMemoryProjection(
            revision: try integer(value["revision"], label: "working_memory revision"),
            goal: goal,
            fields: fields,
            filesEvidence: try objectArray(value["files_evidence"], label: "files_evidence")
        )
    }

    private static func stringArray(
        _ value: NativeJSONValue?, label: String
    ) throws -> [String] {
        guard case .array(let values) = value else {
            throw NativeProjectionError("\(label) must be an array")
        }
        return try values.map { try string($0, label: "\(label) item") }
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
