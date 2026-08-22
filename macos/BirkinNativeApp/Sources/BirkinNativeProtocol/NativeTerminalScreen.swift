struct NativeTerminalScreen: Equatable, Sendable {
    private static let coordinateLimit = 4_096

    var lines: [[Character]] = [[]]
    var row = 0
    var column = 0
    private var savedRow = 0
    private var savedColumn = 0

    mutating func write(_ character: Character) {
        ensureRow()
        while lines[row].count < column { lines[row].append(" ") }
        if column < lines[row].count {
            lines[row][column] = character
        } else {
            lines[row].append(character)
        }
        column = min(column + 1, Self.coordinateLimit)
    }

    mutating func carriageReturn() { column = 0 }

    mutating func lineFeed() {
        row = min(row + 1, Self.coordinateLimit)
        ensureRow()
    }

    mutating func backspace() { column = max(0, column - 1) }

    mutating func tab() {
        column = min(((column / 8) + 1) * 8, Self.coordinateLimit)
    }

    mutating func moveRow(_ delta: Int) {
        row = limited(row + delta)
        ensureRow()
    }

    mutating func moveColumn(_ delta: Int) {
        column = limited(column + delta)
    }

    mutating func position(row newRow: Int? = nil, column newColumn: Int? = nil) {
        if let newRow { row = limited(newRow) }
        if let newColumn { column = limited(newColumn) }
        ensureRow()
    }

    mutating func eraseLine(_ mode: Int) {
        ensureRow()
        switch mode {
        case 1:
            let end = min(column + 1, lines[row].count)
            if end > 0 { lines[row].replaceSubrange(0..<end, with: repeatElement(" ", count: end)) }
        case 2:
            lines[row].removeAll(keepingCapacity: true)
        default:
            if column < lines[row].count { lines[row].removeSubrange(column...) }
        }
    }

    mutating func eraseDisplay(_ mode: Int) {
        ensureRow()
        switch mode {
        case 1:
            for index in 0..<row { lines[index].removeAll(keepingCapacity: true) }
            eraseLine(1)
        case 2, 3:
            lines = [[]]
            row = 0
            column = 0
        default:
            eraseLine(0)
            if row + 1 < lines.count { lines.removeSubrange((row + 1)...) }
        }
    }

    mutating func saveCursor() {
        savedRow = row
        savedColumn = column
    }

    mutating func restoreCursor() {
        row = savedRow
        column = savedColumn
        ensureRow()
    }

    mutating func bound(to maximumBytes: Int) {
        var excess = rendered.utf8.count - maximumBytes
        while excess > 0, lines.count > 1 {
            excess -= String(lines.removeFirst()).utf8.count + 1
            row = max(0, row - 1)
            savedRow = max(0, savedRow - 1)
        }
        guard excess > 0, !lines[0].isEmpty else { return }
        var removedBytes = 0
        var removedCharacters = 0
        for character in lines[0] {
            removedBytes += String(character).utf8.count
            removedCharacters += 1
            if removedBytes >= excess { break }
        }
        lines[0].removeFirst(min(removedCharacters, lines[0].count))
        if row == 0 { column = max(0, column - removedCharacters) }
        if savedRow == 0 { savedColumn = max(0, savedColumn - removedCharacters) }
    }

    var rendered: String {
        var renderedLines = lines.map { line -> String in
            var trimmed = line
            while trimmed.last == " " { trimmed.removeLast() }
            return String(trimmed)
        }
        while renderedLines.count > 1, renderedLines.last?.isEmpty == true {
            renderedLines.removeLast()
        }
        return renderedLines.joined(separator: "\n")
    }

    private mutating func ensureRow() {
        while lines.count <= row { lines.append([]) }
    }

    private func limited(_ value: Int) -> Int {
        min(max(0, value), Self.coordinateLimit)
    }
}
