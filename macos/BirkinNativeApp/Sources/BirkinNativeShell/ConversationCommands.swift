import BirkinNativeProtocol
import Foundation

public enum ConversationCommand: Equatable, Sendable {
    case steer(String)
    case interrupt
    case resume
    case retry

    public var commandType: String {
        switch self {
        case .steer: "chat.steer"
        case .interrupt: "chat.interrupt"
        case .resume: "chat.resume"
        case .retry: "chat.retry"
        }
    }
}

public struct ConversationTurnState: Equatable, Sendable {
    public let canSend: Bool
    public let canInterrupt: Bool
    public let canResume: Bool
    public let hasFailedIntent: Bool

    public init(
        canSend: Bool,
        canInterrupt: Bool,
        canResume: Bool,
        hasFailedIntent: Bool
    ) {
        self.canSend = canSend
        self.canInterrupt = canInterrupt
        self.canResume = canResume
        self.hasFailedIntent = hasFailedIntent
    }

    public init(projection: NativeProjectionState, hasFailedIntent: Bool) {
        self.init(
            canSend: projection.composer.canSend,
            canInterrupt: projection.composer.canInterrupt,
            canResume: projection.composer.canResume,
            hasFailedIntent: hasFailedIntent
        )
    }
}

public struct ConversationControlAvailability: Equatable, Sendable {
    public let isEnabled: Bool
    public let disabledReason: String?
}

public enum ConversationCommandError: Error, Equatable, Sendable {
    case emptySteer
}

public enum ConversationCommandFactory {
    public static func availability(
        for command: ConversationCommand,
        turn: ConversationTurnState,
        mutation: MutationAvailability,
        session: NativeReadySession
    ) -> ConversationControlAvailability {
        guard mutation.isEnabled else {
            return disabled(mutation.disabledReason ?? "Connection is not ready.")
        }
        guard session.supportedCommands.contains(command.commandType) else {
            return disabled("\(command.commandType) is not advertised by Python.")
        }
        switch command {
        case .steer(let text):
            guard turn.canInterrupt else { return disabled("There is no active turn to steer.") }
            guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                return disabled("Enter steering guidance.")
            }
        case .interrupt:
            guard turn.canInterrupt else { return disabled("There is no active turn to interrupt.") }
        case .resume:
            guard turn.canResume else { return disabled("The turn is not interrupted.") }
        case .retry:
            guard turn.canSend, turn.hasFailedIntent else {
                return disabled("There is no failed turn to retry.")
            }
        }
        return ConversationControlAvailability(isEnabled: true, disabledReason: nil)
    }

    public static func request(
        for command: ConversationCommand,
        expectedCursor: Int,
        session: NativeReadySession,
        viewID: String = "conversation"
    ) throws -> NativeCommandRequest {
        var payload: NativeJSONObject = [:]
        if case .steer(let text) = command {
            let cleaned = text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !cleaned.isEmpty else { throw ConversationCommandError.emptySteer }
            payload = ["text": .string(cleaned)]
        }
        let id = UUID().uuidString.lowercased()
        return NativeCommandRequest(
            frameID: "command-\(id)", commandID: id,
            expectedCursor: expectedCursor, commandType: command.commandType,
            payload: payload, sessionCapability: session.sessionCapability,
            viewID: viewID
        )
    }

    private static func disabled(_ reason: String) -> ConversationControlAvailability {
        ConversationControlAvailability(isEnabled: false, disabledReason: reason)
    }
}
