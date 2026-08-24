import BirkinNativeProtocol
import Foundation

/// A shell control that submits a canonical command on its own.
///
/// Conversation, terminal, approval, and product-surface controls each carry
/// their own payload-bearing model, so they are not represented here: a case
/// in this enum must always be able to build a complete command.
public enum ShellMutationControl: String, CaseIterable, Sendable {
    case newSession
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
}
