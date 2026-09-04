public struct NativeTerminalProjection: Equatable, Sendable, Identifiable {
    private enum CanonicalParserState {
        case text
        case escape
        case csi
        case osc(escapePending: Bool)
    }

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
        let combined = canonicalScreen + data
        if combined.utf8.count <= NativeTerminalRenderer.maximumScreenBytes {
            canonicalScreen = combined
            renderer.append(data)
        } else {
            canonicalScreen = Self.boundedCanonicalScreen(combined)
            renderer = NativeTerminalRenderer()
            renderer.append(canonicalScreen)
        }
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
        let maximumBytes = NativeTerminalRenderer.maximumScreenBytes
        let totalBytes = value.utf8.count
        guard totalBytes > maximumBytes else { return value }

        var parserState = CanonicalParserState.text
        var consumedBytes = 0
        var index = value.unicodeScalars.startIndex
        while index != value.unicodeScalars.endIndex {
            let scalar = value.unicodeScalars[index]
            if totalBytes - consumedBytes <= maximumBytes,
               case .text = parserState {
                return String(value[index...])
            }
            consumedBytes += scalar.utf8.count
            parserState = nextParserState(after: scalar, from: parserState)
            value.unicodeScalars.formIndex(after: &index)
        }
        return ""
    }

    private static func nextParserState(
        after scalar: Unicode.Scalar,
        from state: CanonicalParserState
    ) -> CanonicalParserState {
        switch state {
        case .text:
            switch scalar.value {
            case 0x1B: return .escape
            case 0x9B: return .csi
            case 0x9D: return .osc(escapePending: false)
            default: return .text
            }
        case .escape:
            switch scalar.value {
            case 0x5B: return .csi
            case 0x5D: return .osc(escapePending: false)
            case 0x1B: return .escape
            default: return .text
            }
        case .csi:
            if (0x40...0x7E).contains(scalar.value) { return .text }
            if (0x20...0x3F).contains(scalar.value) { return .csi }
            return .text
        case .osc(let escapePending):
            if scalar.value == 0x07 || (escapePending && scalar.value == 0x5C) {
                return .text
            }
            return .osc(escapePending: scalar.value == 0x1B)
        }
    }
}
