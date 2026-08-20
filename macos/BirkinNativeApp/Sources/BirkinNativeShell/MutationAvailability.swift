import BirkinNativeProtocol
import Foundation

public enum ShellMutationControl: String, CaseIterable, Sendable {
    case newSession
    case sendMessage
    case newTerminal
    case terminalInput
    case terminalInterrupt
    case terminalClose
}

public struct MutationAvailability: Equatable, Sendable {
    public let isEnabled: Bool
    public let disabledReason: String?

    public init(state: NativeConnectionState, now: Date = Date()) {
        switch state {
        case .ready(let session), .fallback(.ready(let session)):
            if session.hasLiveCapability(at: now) {
                isEnabled = true
                disabledReason = nil
            } else {
                isEnabled = false
                disabledReason = "Connection capability expired."
            }
        case .disconnected:
            isEnabled = false
            disabledReason = "Disconnected from the Python authority."
        case .replaying:
            isEnabled = false
            disabledReason = "Canonical state is replaying."
        case .failed(let reason):
            isEnabled = false
            disabledReason = String(reason.prefix(160))
        case .connecting, .negotiating, .fallback:
            isEnabled = false
            disabledReason = "Connection is not ready."
        }
    }

    public func allows(_ control: ShellMutationControl) -> Bool {
        isEnabled
    }
}
