import AppKit
import Foundation
import SwiftUI
import Testing

@testable import BirkinNativeProtocol
@testable import BirkinNativeShell

@Suite("Real Swift to Python terminal round trip")
struct NativeTerminalRoundTripIntegrationTests {
    @MainActor
    @Test("Swift command reaches PTY and Python output reaches projection")
    func echoRoundTrip() throws {
        let harness = try HarnessReadiness.launch(
            transport: "uds",
            options: HarnessLaunchOptions(terminal: true)
        )
        guard let socketPath = harness.record["socket_path"] as? String else {
            throw HarnessError.malformedReadiness
        }
        let socket = try NativeSocket.connectUDS(path: socketPath)
        let hello = integrationHello.envelope(bootstrapSecret: nil)
        try socket.send(NativeFrameCodec.encode(hello))
        let ready = try receive(socket)
        let capability = try object(ready.body["capability"])
        let token = try string(capability["token"])
        let connectionCapability = NativeProjectionCapability(
            token,
            surface: integrationHello.surface,
            viewID: integrationHello.viewID
        )
        let subscribe = NativeEnvelope(kind: .subscribe, id: "terminal-subscribe", body: [
            "session_id": .string("session-1"),
            "after_cursor": .int(0),
            "known_instance_id": .null,
            "session_capability": .string(token),
            "surfaces": .object([:]),
        ])
        try socket.send(NativeFrameCodec.encode(subscribe))
        let snapshot = try receive(socket)
        let store = NativeProjectionStore()
        try store.apply(snapshot: snapshot)

        let create = NativeCommandRequest(
            frameID: "terminal-create-frame", commandID: "terminal-create",
            expectedCursor: 0, commandType: "terminal.create",
            payload: [
                "actor_kind": .string("native_human"),
                "cwd": .string(harness.root.path),
            ],
            sessionCapability: token, viewID: "terminal-integration"
        )
        try socket.send(NativeFrameCodec.encode(
            connectionCapability.commandEnvelope(for: create)
        ))
        let createReceipt = try receiveKind(.receipt, socket: socket)
        let createCursor = try integer(createReceipt.body["result_event_cursor"])
        let createResult = try object(createReceipt.body["result"])
        let terminalID = try string(createResult["terminal_id"])
        let lease = try string(createResult["lease"])
        let createEvents = try receiveEvents(through: createCursor, socket: socket, store: store)
        let opened = try #require(createEvents.first { $0.body.string("type") == "terminal.opened" })
        let openedPayload = try object(opened.body["payload"])
        #expect(try string(openedPayload["lease"]) == "[REDACTED]")

        let input = NativeCommandRequest(
            frameID: "terminal-input-frame", commandID: "terminal-input",
            expectedCursor: createCursor, commandType: "terminal.input",
            payload: [
                "terminal_id": .string(terminalID), "lease": .string(lease),
                "sequence": .int(1), "data": .string("printf 'hello-native\\n'\n"),
            ],
            sessionCapability: token, viewID: "terminal-integration"
        )
        try socket.send(NativeFrameCodec.encode(
            connectionCapability.commandEnvelope(for: input)
        ))
        let inputReceipt = try receiveKind(.receipt, socket: socket)
        let inputCursor = try integer(inputReceipt.body["result_event_cursor"])
        let inputEvents = try receiveEvents(through: inputCursor, socket: socket, store: store)
        let output = try #require(inputEvents.first { $0.body.string("type") == "terminal.output" })
        let outputPayload = try object(output.body["payload"])
        let transcript = try string(outputPayload["data"])
        #expect(transcript.contains("hello-native"))
        #expect(store.projection?.terminals.first?.screen.contains("hello-native") == true)

        let close = NativeCommandRequest(
            frameID: "terminal-close-frame", commandID: "terminal-close",
            expectedCursor: inputCursor, commandType: "terminal.close",
            payload: ["terminal_id": .string(terminalID), "lease": .string(lease)],
            sessionCapability: token, viewID: "terminal-integration"
        )
        try socket.send(NativeFrameCodec.encode(
            connectionCapability.commandEnvelope(for: close)
        ))
        let closeReceipt = try receiveKind(.receipt, socket: socket)
        let closeCursor = try integer(closeReceipt.body["result_event_cursor"])
        _ = try receiveEvents(through: closeCursor, socket: socket, store: store)
        #expect(store.projection?.terminals.first?.state == "exited")

        let evidence = harness.root.appendingPathComponent("swift-terminal-transcript.txt")
        try transcript.write(to: evidence, atomically: true, encoding: .utf8)
        let durableEvidence = evidenceDirectory().appendingPathComponent(
            "swift-terminal-round-trip.txt"
        )
        try FileManager.default.createDirectory(
            at: durableEvidence.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        try transcript.write(to: durableEvidence, atomically: true, encoding: .utf8)
        let terminal = try #require(store.projection?.terminals.first)
        let screenshotView = TerminalView(
            terminal: NativeTerminalProjection(
                terminalID: terminal.terminalID, cwd: terminal.cwd, screen: transcript,
                outputSequence: terminal.outputSequence, state: terminal.state,
                exitStatus: terminal.exitStatus, columns: terminal.columns, rows: terminal.rows,
                lease: nil, readOnly: true
            ),
            canMutate: false, sendInput: { _ in }, interrupt: {}, close: {}
        ).frame(width: 720, height: 420)
        let renderer = ImageRenderer(content: screenshotView)
        let image = try #require(renderer.nsImage)
        let tiff = try #require(image.tiffRepresentation)
        let bitmap = try #require(NSBitmapImageRep(data: tiff))
        let png = try #require(bitmap.representation(using: .png, properties: [:]))
        try png.write(
            to: evidenceDirectory().appendingPathComponent("terminal-round-trip.png"),
            options: .atomic
        )
        print("SWIFT TERMINAL RENDERED \(terminal.screen.debugDescription)")

        socket.close()
        print("SWIFT TERMINAL CLEANUP \(try harness.finish()) root_removed=true")
    }

    private func receive(_ socket: NativeSocket) throws -> NativeEnvelope {
        try NativeFrameCodec.decode(frame: socket.receiveFrame())
    }

    private func receiveKind(
        _ kind: NativeMessageKind,
        socket: NativeSocket
    ) throws -> NativeEnvelope {
        for _ in 0..<32 {
            let message = try receive(socket)
            if message.kind == kind { return message }
        }
        throw NativeTransportError("terminal integration response missing")
    }

    private func receiveEvents(
        through cursor: Int,
        socket: NativeSocket,
        store: NativeProjectionStore
    ) throws -> [NativeEnvelope] {
        var events: [NativeEnvelope] = []
        while (store.latestAppliedCursor ?? 0) < cursor {
            let message = try receive(socket)
            if message.kind == .event {
                try store.apply(event: message)
                events.append(message)
            }
        }
        return events
    }

    private func object(_ value: NativeJSONValue?) throws -> NativeJSONObject {
        guard case .object(let object) = value else {
            throw NativeTransportError("terminal integration object missing")
        }
        return object
    }

    private func string(_ value: NativeJSONValue?) throws -> String {
        guard case .string(let string) = value else {
            throw NativeTransportError("terminal integration string missing")
        }
        return string
    }

    private func integer(_ value: NativeJSONValue?) throws -> Int {
        guard case .int(let integer) = value else {
            throw NativeTransportError("terminal integration integer missing")
        }
        return integer
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
}
