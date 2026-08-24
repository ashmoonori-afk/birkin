import AppKit
import BirkinNativeProtocol
import SwiftUI
import Testing

@testable import BirkinNativeShell

@Suite("Owned terminal controls")
@MainActor
struct TerminalControlsTests {
    @Test("keyboard input delegates to Python with lease and sequence")
    func inputDelegates() {
        let terminal = liveTerminal()
        let model = TerminalControlModel()
        var requests: [NativeCommandRequest] = []

        let sent = model.sendInput(
            "echo hello-native\n",
            terminal: terminal,
            expectedCursor: 20,
            sessionCapability: "capability",
            submit: { requests.append($0) }
        )

        #expect(sent)
        #expect(requests.count == 1)
        #expect(requests[0].commandType == "terminal.input")
        #expect(requests[0].payload.string("terminal_id") == "terminal-1")
        #expect(requests[0].payload.string("lease") == "lease-1")
        #expect(requests[0].payload.integer("sequence") == 1)
        #expect(requests[0].payload.string("data") == "echo hello-native\n")
    }

    @Test("interrupt and confirmed close delegate; unconfirmed close does not")
    func lifecycleControlsDelegate() {
        let terminal = liveTerminal()
        let model = TerminalControlModel()
        var requests: [NativeCommandRequest] = []
        let submit: (NativeCommandRequest) -> Void = { requests.append($0) }

        #expect(model.interrupt(
            terminal: terminal, expectedCursor: 21,
            sessionCapability: "capability", submit: submit
        ))
        #expect(!model.close(
            terminal: terminal, confirmed: false, expectedCursor: 22,
            sessionCapability: "capability", submit: submit
        ))
        #expect(model.close(
            terminal: terminal, confirmed: true, expectedCursor: 22,
            sessionCapability: "capability", submit: submit
        ))
        #expect(requests.map(\.commandType) == ["terminal.signal", "terminal.close"])
        #expect(requests[0].payload.string("signal") == "INT")
    }

    @Test("presentation authority exposes controls only for a mutable leased terminal")
    func presentationAuthority() {
        let live = TerminalPresentationAuthority(
            terminal: liveTerminal(), capabilityAllowsMutation: true
        )
        #expect(live.visibleMutationControls == Set(TerminalMutationControl.allCases))
        #expect(!live.showsReadOnlyReplayLabel)

        let noCapability = TerminalPresentationAuthority(
            terminal: liveTerminal(), capabilityAllowsMutation: false
        )
        #expect(noCapability.visibleMutationControls.isEmpty)

        for terminal in [
            liveTerminal(state: "exited"),
            liveTerminal(lease: nil),
            liveTerminal(readOnly: true),
        ] {
            let replay = TerminalPresentationAuthority(
                terminal: terminal, capabilityAllowsMutation: true
            )
            #expect(replay.visibleMutationControls.isEmpty)
            #expect(replay.showsReadOnlyReplayLabel == terminal.readOnly)
        }
    }

    @Test("read-only terminal view has a replay-only presentation")
    func readOnlyPresentation() {
        let terminal = liveTerminal(lease: nil, readOnly: true)
        let authority = TerminalPresentationAuthority(
            terminal: terminal, capabilityAllowsMutation: true
        )
        #expect(authority.visibleMutationControls.isEmpty)
        #expect(authority.statusLabel == "Read-only replay")
    }

    @Test("terminal surface renders real transcript screenshot")
    func screenshotEvidence() throws {
        let view = TerminalView(
            terminal: liveTerminal(screen: "$ echo hello-native\nhello-native\n"),
            canMutate: true,
            sendInput: { _ in }, interrupt: {}, close: {}
        )
        .frame(width: 720, height: 420)
        let renderer = ImageRenderer(content: view)
        let image = try #require(renderer.nsImage)
        let tiff = try #require(image.tiffRepresentation)
        let bitmap = try #require(NSBitmapImageRep(data: tiff))
        let png = try #require(bitmap.representation(using: .png, properties: [:]))
        let output = evidenceDirectory().appendingPathComponent("terminal-round-trip.png")
        try FileManager.default.createDirectory(
            at: output.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        try png.write(to: output, options: .atomic)
        #expect(png.count > 10_000)
    }

    private func liveTerminal(
        screen: String = "",
        state: String = "running",
        lease: String? = "lease-1",
        readOnly: Bool = false
    ) -> NativeTerminalProjection {
        NativeTerminalProjection(
            terminalID: "terminal-1", cwd: "/private/workspace", screen: screen,
            outputSequence: 0, state: state, exitStatus: nil,
            columns: 80, rows: 24, lease: lease, readOnly: readOnly
        )
    }

    private func evidenceDirectory() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent(".omo/evidence/native-shell")
    }
}

private extension NativeJSONObject {
    func string(_ key: String) -> String? {
        guard case .string(let value) = self[key] else { return nil }
        return value
    }

    func integer(_ key: String) -> Int? {
        guard case .int(let value) = self[key] else { return nil }
        return value
    }
}
