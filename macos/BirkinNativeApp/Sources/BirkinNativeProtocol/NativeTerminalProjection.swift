public struct NativeTerminalProjection: Equatable, Sendable, Identifiable {
    public let terminalID: String
    public var cwd: String
    public var screen: String
    public var outputSequence: Int
    public var state: String
    public var exitStatus: Int?
    public var columns: Int
    public var rows: Int
    public var lease: String?
    public var readOnly: Bool

    public var id: String { terminalID }

    public init(
        terminalID: String,
        cwd: String,
        screen: String,
        outputSequence: Int,
        state: String,
        exitStatus: Int?,
        columns: Int,
        rows: Int,
        lease: String?,
        readOnly: Bool
    ) {
        self.terminalID = terminalID
        self.cwd = cwd
        self.screen = screen
        self.outputSequence = outputSequence
        self.state = state
        self.exitStatus = exitStatus
        self.columns = columns
        self.rows = rows
        self.lease = lease
        self.readOnly = readOnly
    }

    var canonicalJSON: NativeJSONObject {
        [
            "terminal_id": .string(terminalID),
            "cwd": .string(cwd),
            "screen": .string(screen),
            "output_sequence": .int(outputSequence),
            "state": .string(state),
            "exit_status": exitStatus.map(NativeJSONValue.int) ?? .null,
            "columns": .int(columns),
            "rows": .int(rows),
            "lease": lease.map(NativeJSONValue.string) ?? .null,
            "read_only": .bool(readOnly),
        ]
    }
}
