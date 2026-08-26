public struct NativeTerminalProjection: Equatable, Sendable, Identifiable {
    public let terminalID: String
    public var cwd: String
    private var canonicalScreen: String
    private var renderer: NativeTerminalRenderer
    public var outputSequence: Int
    public var state: String
    public var exitStatus: Int?
    public var columns: Int
    public var rows: Int
    public var lease: String?
    public var readOnly: Bool

    public var id: String { terminalID }

    public var screen: String { renderer.screen }

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
        let boundedScreen = Self.boundedCanonicalScreen(screen)
        self.terminalID = terminalID
        self.cwd = cwd
        canonicalScreen = boundedScreen
        renderer = NativeTerminalRenderer()
        renderer.append(boundedScreen)
        self.outputSequence = outputSequence
        self.state = state
        self.exitStatus = exitStatus
        self.columns = columns
        self.rows = rows
        self.lease = lease
        self.readOnly = readOnly
    }

    mutating func appendOutput(_ data: String) {
        canonicalScreen = Self.boundedCanonicalScreen(canonicalScreen + data)
        renderer.append(data)
    }

    public static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.terminalID == rhs.terminalID
            && lhs.cwd == rhs.cwd
            && lhs.canonicalScreen == rhs.canonicalScreen
            && lhs.screen == rhs.screen
            && lhs.outputSequence == rhs.outputSequence
            && lhs.state == rhs.state
            && lhs.exitStatus == rhs.exitStatus
            && lhs.columns == rhs.columns
            && lhs.rows == rhs.rows
            && lhs.lease == rhs.lease
            && lhs.readOnly == rhs.readOnly
    }

    var canonicalJSON: NativeJSONObject {
        [
            "terminal_id": .string(terminalID),
            "cwd": .string(cwd),
            "screen": .string(canonicalScreen),
            "output_sequence": .int(outputSequence),
            "state": .string(state),
            "exit_status": exitStatus.map(NativeJSONValue.int) ?? .null,
            "columns": .int(columns),
            "rows": .int(rows),
            "lease": lease.map(NativeJSONValue.string) ?? .null,
            "read_only": .bool(readOnly),
        ]
    }

    private static func boundedCanonicalScreen(_ value: String) -> String {
        let bytes = Array(value.utf8)
        guard bytes.count > NativeTerminalRenderer.maximumScreenBytes else { return value }
        return String(
            decoding: bytes.suffix(NativeTerminalRenderer.maximumScreenBytes),
            as: UTF8.self
        )
    }
}
