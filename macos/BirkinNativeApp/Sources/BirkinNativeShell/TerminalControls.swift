import BirkinNativeProtocol
import SwiftUI

@MainActor
public final class TerminalControlModel: ObservableObject {
    @Published public private(set) var visibleReason: String?
    private var inputSequences: [String: Int] = [:]
    public init() {}
    @discardableResult
    public func requestTerminal(
        cwd: String = ".",
        approvalID: String? = nil,
        expectedCursor: Int,
        sessionCapability: String,
        submit: (NativeCommandRequest) -> Void
    ) -> Bool {
        let payload: NativeJSONObject
        if let approvalID {
            payload = [
                "actor_kind": .string("native_human"),
                "cwd": .string(cwd),
                "approval_id": .string(approvalID),
            ]
        } else {
            payload = [
                "actor_kind": .string("native_human"),
                "cwd": .string(cwd),
            ]
        }
        submit(
            request(
                type: "terminal.create", payload: payload,
                expectedCursor: expectedCursor, sessionCapability: sessionCapability
            ))
        visibleReason = nil
        return true
    }
    @discardableResult
    public func sendInput(
        _ data: String,
        terminal: NativeTerminalProjection,
        expectedCursor: Int,
        sessionCapability: String,
        submit: (NativeCommandRequest) -> Void
    ) -> Bool {
        guard let lease = liveLease(terminal) else { return false }
        let byteCount = data.utf8.count
        guard byteCount > 0, byteCount <= 4_096 else {
            visibleReason = "Terminal input must be between 1 and 4096 bytes."
            return false
        }
        let sequence = (inputSequences[terminal.terminalID] ?? 0) + 1
        inputSequences[terminal.terminalID] = sequence
        submit(
            request(
                type: "terminal.input",
                payload: [
                    "terminal_id": .string(terminal.terminalID),
                    "lease": .string(lease),
                    "sequence": .int(sequence),
                    "data": .string(data),
                ],
                expectedCursor: expectedCursor,
                sessionCapability: sessionCapability
            ))
        visibleReason = nil
        return true
    }
    @discardableResult
    public func interrupt(
        terminal: NativeTerminalProjection,
        expectedCursor: Int,
        sessionCapability: String,
        submit: (NativeCommandRequest) -> Void
    ) -> Bool {
        guard let lease = liveLease(terminal) else { return false }
        submit(
            request(
                type: "terminal.signal",
                payload: [
                    "terminal_id": .string(terminal.terminalID),
                    "lease": .string(lease),
                    "signal": .string("INT"),
                ],
                expectedCursor: expectedCursor,
                sessionCapability: sessionCapability
            ))
        visibleReason = nil
        return true
    }
    @discardableResult
    public func close(
        terminal: NativeTerminalProjection,
        confirmed: Bool,
        expectedCursor: Int,
        sessionCapability: String,
        submit: (NativeCommandRequest) -> Void
    ) -> Bool {
        guard confirmed, let lease = liveLease(terminal) else { return false }
        submit(
            request(
                type: "terminal.close",
                payload: [
                    "terminal_id": .string(terminal.terminalID),
                    "lease": .string(lease),
                ],
                expectedCursor: expectedCursor,
                sessionCapability: sessionCapability
            ))
        visibleReason = nil
        return true
    }

    private func liveLease(_ terminal: NativeTerminalProjection) -> String? {
        guard terminal.state == "running", !terminal.readOnly,
            let lease = terminal.lease, !lease.isEmpty
        else {
            visibleReason = "A live Python terminal lease is required."
            return nil
        }
        return lease
    }

    private func request(
        type: String,
        payload: NativeJSONObject,
        expectedCursor: Int,
        sessionCapability: String
    ) -> NativeCommandRequest {
        let id = "terminal-\(UUID().uuidString.lowercased())"
        return NativeCommandRequest(
            frameID: "frame-\(id)", commandID: id,
            expectedCursor: expectedCursor, commandType: type, payload: payload,
            sessionCapability: sessionCapability, viewID: "owned-terminal"
        )
    }
}

public struct TerminalView: View {
    public let terminal: NativeTerminalProjection
    public let canMutate: Bool
    private let sendInput: (String) -> Void
    private let interrupt: () -> Void
    private let close: () -> Void

    @State private var input = ""
    @State private var confirmsClose = false

    public init(
        terminal: NativeTerminalProjection,
        canMutate: Bool,
        sendInput: @escaping (String) -> Void,
        interrupt: @escaping () -> Void,
        close: @escaping () -> Void
    ) {
        self.terminal = terminal
        self.canMutate = canMutate
        self.sendInput = sendInput
        self.interrupt = interrupt
        self.close = close
    }

    public init(
        terminal: NativeTerminalProjection, presentationAuthority: TerminalPresentationAuthority,
        sendInput: @escaping (String) -> Void, interrupt: @escaping () -> Void,
        close: @escaping () -> Void
    ) {
        self.init(
            terminal: terminal, canMutate: presentationAuthority.shows(.input),
            sendInput: sendInput, interrupt: interrupt, close: close)
    }

    public var presentationAuthority: TerminalPresentationAuthority {
        TerminalPresentationAuthority(
            terminal: terminal, capabilityAllowsMutation: canMutate
        )
    }

    @ViewBuilder
    public var body: some View {
        if presentationAuthority.shows(.closeConfirmation) {
            terminalContent.confirmationDialog(
                "Close this Python-owned terminal?",
                isPresented: $confirmsClose,
                titleVisibility: .visible
            ) {
                Button("Close Terminal", role: .destructive, action: close)
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("The Python process tree will be terminated and cannot be resurrected.")
            }
        } else {
            terminalContent
        }
    }

    private var terminalContent: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(terminal.terminalID).font(.caption.monospaced())
                    Text(terminal.cwd).font(.caption2).foregroundStyle(.secondary)
                }
                Spacer()
                Text(presentationAuthority.statusLabel).font(.caption.bold())
                if presentationAuthority.shows(.interrupt) {
                    Button("Interrupt", action: interrupt)
                        .keyboardShortcut(".", modifiers: .command)
                        .accessibilityLabel("Interrupt Python terminal")
                }
                if presentationAuthority.shows(.close) {
                    Button("Close") { confirmsClose = true }
                        .accessibilityLabel("Close Python terminal")
                }
            }
            ScrollView([.vertical, .horizontal]) { terminalText }
            if presentationAuthority.shows(.input), presentationAuthority.shows(.run) {
                HStack {
                    TextField("Terminal input", text: $input)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit { submitInput() }
                        .accessibilityLabel("Terminal input")
                    Button("Run", action: submitInput)
                        .disabled(input.isEmpty)
                        .accessibilityLabel("Run terminal input")
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Python terminal")
    }

    private var terminalText: some View {
        Text(terminal.screen.isEmpty ? "Terminal ready." : terminal.screen)
            .font(.system(.body, design: .monospaced))
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .padding(8)
            .background(Color.black.opacity(0.86), in: RoundedRectangle(cornerRadius: 6))
            .foregroundStyle(Color.green)
            .accessibilityLabel("Terminal text snapshot")
    }

    private func submitInput() {
        guard !input.isEmpty else { return }
        let value = input.hasSuffix("\n") ? input : input + "\n"
        sendInput(value)
        input = ""
    }
}
