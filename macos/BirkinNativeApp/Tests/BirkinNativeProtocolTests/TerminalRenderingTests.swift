import Testing

@testable import BirkinNativeProtocol

@Suite("Incremental terminal rendering")
struct TerminalRenderingTests {
    @Test("control sequences update a plain-text screen across chunk boundaries")
    func controlsAcrossChunks() {
        var renderer = NativeTerminalRenderer()
        renderer.append("abc\rY\u{8}Z\t끝\r\nsecond")
        renderer.append("\u{1B}[")
        renderer.append("1;2HQ\u{1B}[K")

        #expect(renderer.screen == "ZQ\nsecond")
        #expect(!renderer.screen.unicodeScalars.contains(where: {
            ($0.value < 0x20 && $0.value != 0x0A) || (0x7F...0x9F).contains($0.value)
        }))
    }

    @Test("cursor movement and erase commands mutate the screen")
    func cursorAndErase() {
        var renderer = NativeTerminalRenderer()
        renderer.append("first\r\nsecond\u{1B}[2D\u{1B}[K")
        #expect(renderer.screen == "first\nseco")

        renderer.append("\u{1B}[2Jhome")
        #expect(renderer.screen == "home")
    }

    @Test("SGR, OSC BEL, and OSC ST payloads never enter rendered text")
    func stripsNonTextSequences() {
        var renderer = NativeTerminalRenderer()
        renderer.append("\u{1B}[31mred\u{1B}[0m\u{1B}]0;secret")
        renderer.append(" title\u{7}ok\u{1B}]8;;https://secret.example\u{1B}")
        renderer.append("\\link\u{1B}]broken\u{1B}\\done")

        #expect(renderer.screen == "redoklinkdone")
        #expect(!renderer.screen.contains("secret"))
        #expect(!renderer.screen.contains("\u{1B}"))
    }

    @Test("alternate screen restores the primary screen")
    func alternateScreen() {
        var renderer = NativeTerminalRenderer()
        renderer.append("primary\u{1B}[?1049halternate")
        #expect(renderer.screen == "alternate")
        renderer.append("\u{1B}[?1049l resumed")
        #expect(renderer.screen == "primary resumed")
    }

    @Test("malformed and unterminated sequences are bounded and hidden")
    func malformedSequences() {
        var renderer = NativeTerminalRenderer()
        renderer.append("safe\u{1B}[999999999999999999999999999999;xvisible")
        renderer.append("\u{1B}]private unterminated payload")

        #expect(renderer.screen == "safevisible")
        #expect(renderer.pendingControlByteCount <= NativeTerminalRenderer.maximumControlBytes)
    }

    @Test("rendered output remains UTF-8 bounded")
    func boundedOutput() {
        var renderer = NativeTerminalRenderer()
        renderer.append(String(repeating: "한", count: 30_000))

        #expect(renderer.screen.utf8.count <= NativeTerminalRenderer.maximumScreenBytes)
        #expect(renderer.screen.hasSuffix("한한한"))
    }

    @Test("terminal projection separates canonical VT from rendered presentation")
    func projectionIntegration() {
        let raw = "start\u{1B}[31m red\u{1B}[0m\u{1B}[2DOK"
        let terminal = NativeTerminalProjection(
            terminalID: "terminal", cwd: ".", screen: raw,
            outputSequence: 0, state: "running", exitStatus: nil,
            columns: 80, rows: 24, lease: "lease", readOnly: false
        )

        #expect(terminal.screen == "start rOK")
        #expect(terminal.canonicalJSON["screen"] == .string(raw))
        #expect(!terminal.screen.contains("\u{1B}"))
    }

    @Test("canonical bounds are UTF-8 scalar safe and never exceed the byte cap")
    func scalarSafeCanonicalBound() {
        let raw = "한🙂" + String(
            repeating: "a", count: NativeTerminalRenderer.maximumScreenBytes - 2
        )
        let terminal = NativeTerminalProjection(
            terminalID: "terminal", cwd: ".", screen: raw,
            outputSequence: 0, state: "running", exitStatus: nil,
            columns: 80, rows: 24, lease: nil, readOnly: true
        )
        guard case .string(let canonical) = terminal.canonicalJSON["screen"] else {
            Issue.record("canonical terminal screen is missing")
            return
        }

        #expect(canonical.utf8.count <= NativeTerminalRenderer.maximumScreenBytes)
        #expect(!canonical.contains("\u{FFFD}"))
        #expect(canonical == String(
            repeating: "a", count: NativeTerminalRenderer.maximumScreenBytes - 2
        ))
    }

    @Test("canonical bounds do not reconnect in the middle of a VT sequence")
    func parserSafeCanonicalBound() {
        let visible = String(
            repeating: "a", count: NativeTerminalRenderer.maximumScreenBytes - 2
        )
        let terminal = NativeTerminalProjection(
            terminalID: "terminal", cwd: ".", screen: "\u{1B}[31m" + visible,
            outputSequence: 0, state: "running", exitStatus: nil,
            columns: 80, rows: 24, lease: nil, readOnly: true
        )

        #expect(terminal.canonicalJSON["screen"] == .string(visible))
        #expect(!terminal.screen.isEmpty)
        #expect(!terminal.screen.hasPrefix("1m"))
        #expect(Set(terminal.screen) == ["a"])
    }

    @Test("canonical terminal state recreates the same rendered reconnect state")
    func reconnectRoundTrip() throws {
        let live = NativeTerminalProjection(
            terminalID: "terminal", cwd: ".",
            screen: "prompt> work\rDONE\u{1B}[31m!\u{1B}[0m",
            outputSequence: 2, state: "running", exitStatus: nil,
            columns: 80, rows: 24, lease: nil, readOnly: true
        )
        guard case .string(let raw) = live.canonicalJSON["screen"] else {
            Issue.record("canonical terminal screen is missing")
            return
        }
        let reconnected = NativeTerminalProjection(
            terminalID: live.terminalID, cwd: live.cwd, screen: raw,
            outputSequence: live.outputSequence, state: live.state,
            exitStatus: live.exitStatus, columns: live.columns, rows: live.rows,
            lease: live.lease, readOnly: live.readOnly
        )

        #expect(reconnected == live)
        #expect(reconnected.screen == "DONE!t> work")
    }
}
