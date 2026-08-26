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

    @Test("terminal projection sanitizes snapshots and incrementally appended output")
    func projectionIntegration() {
        var terminal = NativeTerminalProjection(
            terminalID: "terminal", cwd: ".", screen: "start\u{1B}[31m red\u{1B}[0m",
            outputSequence: 0, state: "running", exitStatus: nil,
            columns: 80, rows: 24, lease: "lease", readOnly: false
        )
        terminal.appendOutput("\u{1B}[")
        terminal.appendOutput("2DOK")

        #expect(terminal.screen == "start rOK")
        #expect(!terminal.screen.contains("\u{1B}"))
    }

    @Test("terminal projection preserves a raw snapshot separately from presentation")
    func projectionPreservesCanonicalSnapshot() {
        let raw = "hello-native\r\n\u{1B}[31m"
        let terminal = NativeTerminalProjection(
            terminalID: "terminal", cwd: ".", screen: raw,
            outputSequence: 0, state: "running", exitStatus: nil,
            columns: 80, rows: 24, lease: "lease", readOnly: false
        )

        #expect(terminal.canonicalJSON["screen"] == .string(raw))
        #expect(terminal.screen == "hello-native")
    }

    @Test("terminal projection preserves raw appended output separately from presentation")
    func projectionPreservesCanonicalOutput() {
        var terminal = NativeTerminalProjection(
            terminalID: "terminal", cwd: ".", screen: "",
            outputSequence: 0, state: "running", exitStatus: nil,
            columns: 80, rows: 24, lease: "lease", readOnly: false
        )
        let raw = "hello-native\r\n\u{1B}[31m"

        terminal.appendOutput(raw)

        #expect(terminal.canonicalJSON["screen"] == .string(raw))
        #expect(terminal.screen == "hello-native")
    }
}
