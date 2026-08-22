public struct NativeTerminalRenderer: Equatable, Sendable {
    public static let maximumScreenBytes = 65_536
    public static let maximumControlBytes = 1_024

    private enum ParserState: Equatable, Sendable {
        case text
        case escape
        case csi(String, overflowed: Bool)
        case osc(count: Int, escapePending: Bool)
    }

    private var primary = NativeTerminalScreen()
    private var alternate = NativeTerminalScreen()
    private var usesAlternate = false
    private var parserState = ParserState.text

    public init() {}

    public var screen: String { activeScreen.rendered }

    public var pendingControlByteCount: Int {
        switch parserState {
        case .text: 0
        case .escape: 1
        case .csi(let value, _): min(Self.maximumControlBytes, value.utf8.count + 2)
        case .osc(let count, _): min(Self.maximumControlBytes, count)
        }
    }

    public mutating func append(_ chunk: String) {
        for scalar in chunk.unicodeScalars { consume(scalar) }
        if usesAlternate {
            alternate.bound(to: Self.maximumScreenBytes)
        } else {
            primary.bound(to: Self.maximumScreenBytes)
        }
    }

    private var activeScreen: NativeTerminalScreen {
        usesAlternate ? alternate : primary
    }

    private mutating func updateScreen(_ body: (inout NativeTerminalScreen) -> Void) {
        if usesAlternate { body(&alternate) } else { body(&primary) }
    }

    private mutating func consume(_ scalar: Unicode.Scalar) {
        switch parserState {
        case .text: consumeText(scalar)
        case .escape: consumeEscape(scalar)
        case .csi(let value, let overflowed):
            consumeCSI(scalar, value: value, overflowed: overflowed)
        case .osc(let count, let escapePending):
            consumeOSC(scalar, count: count, escapePending: escapePending)
        }
    }

    private mutating func consumeText(_ scalar: Unicode.Scalar) {
        switch scalar.value {
        case 0x1B: parserState = .escape
        case 0x9B: parserState = .csi("", overflowed: false)
        case 0x9D: parserState = .osc(count: 1, escapePending: false)
        case 0x08: updateScreen { $0.backspace() }
        case 0x09: updateScreen { $0.tab() }
        case 0x0A...0x0C: updateScreen { $0.lineFeed() }
        case 0x0D: updateScreen { $0.carriageReturn() }
        case 0x00...0x1F, 0x7F...0x9F: break
        default: updateScreen { $0.write(Character(String(scalar))) }
        }
    }

    private mutating func consumeEscape(_ scalar: Unicode.Scalar) {
        switch scalar.value {
        case 0x5B: parserState = .csi("", overflowed: false)
        case 0x5D: parserState = .osc(count: 2, escapePending: false)
        case 0x37:
            updateScreen { $0.saveCursor() }
            parserState = .text
        case 0x38:
            updateScreen { $0.restoreCursor() }
            parserState = .text
        case 0x63:
            primary = NativeTerminalScreen()
            alternate = NativeTerminalScreen()
            usesAlternate = false
            parserState = .text
        case 0x1B: break
        default: parserState = .text
        }
    }

    private mutating func consumeCSI(
        _ scalar: Unicode.Scalar,
        value: String,
        overflowed: Bool
    ) {
        if (0x40...0x7E).contains(scalar.value) {
            if !overflowed { executeCSI(final: Character(String(scalar)), parameters: value) }
            parserState = .text
            return
        }
        guard (0x20...0x3F).contains(scalar.value) else {
            parserState = .text
            return
        }
        guard !overflowed else { return }
        let next = value + String(scalar)
        parserState =
            next.utf8.count + 2 > Self.maximumControlBytes
            ? .csi(value, overflowed: true)
            : .csi(next, overflowed: false)
    }

    private mutating func consumeOSC(
        _ scalar: Unicode.Scalar,
        count: Int,
        escapePending: Bool
    ) {
        if scalar.value == 0x07 || (escapePending && scalar.value == 0x5C) {
            parserState = .text
            return
        }
        let nextCount = min(Self.maximumControlBytes, count + scalar.utf8.count)
        parserState = .osc(count: nextCount, escapePending: scalar.value == 0x1B)
    }

    private mutating func executeCSI(final: Character, parameters raw: String) {
        let isPrivate = raw.first == "?"
        let body = isPrivate ? String(raw.dropFirst()) : raw
        let values = body.split(separator: ";", omittingEmptySubsequences: false).map {
            Int($0.prefix(7))
        }
        let first = values.first.flatMap { $0 } ?? 0
        let amount = max(1, first)
        switch final {
        case "A": updateScreen { $0.moveRow(-amount) }
        case "B": updateScreen { $0.moveRow(amount) }
        case "C": updateScreen { $0.moveColumn(amount) }
        case "D": updateScreen { $0.moveColumn(-amount) }
        case "E":
            updateScreen {
                $0.moveRow(amount)
                $0.carriageReturn()
            }
        case "F":
            updateScreen {
                $0.moveRow(-amount)
                $0.carriageReturn()
            }
        case "G": updateScreen { $0.position(column: amount - 1) }
        case "d": updateScreen { $0.position(row: amount - 1) }
        case "H", "f":
            let row = max(1, values.first.flatMap { $0 } ?? 1) - 1
            let column = max(1, values.dropFirst().first.flatMap { $0 } ?? 1) - 1
            updateScreen { $0.position(row: row, column: column) }
        case "J": updateScreen { $0.eraseDisplay(first) }
        case "K": updateScreen { $0.eraseLine(first) }
        case "s": updateScreen { $0.saveCursor() }
        case "u": updateScreen { $0.restoreCursor() }
        case "h" where isPrivate && values.contains(where: { [47, 1_047, 1_049].contains($0) }):
            alternate = NativeTerminalScreen()
            usesAlternate = true
        case "l" where isPrivate && values.contains(where: { [47, 1_047, 1_049].contains($0) }):
            usesAlternate = false
        default: break
        }
    }
}
