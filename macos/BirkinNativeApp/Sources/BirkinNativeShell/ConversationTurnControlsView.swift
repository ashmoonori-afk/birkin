import BirkinNativeProtocol
import SwiftUI

public struct ConversationTurnControlsView: View {
    public let turn: ConversationTurnState
    public let mutation: MutationAvailability
    public let session: NativeReadySession
    public let expectedCursor: Int
    public let submit: (NativeCommandRequest) -> Void

    @State private var steeringText = ""
    @State private var visibleReason: String?

    public init(
        turn: ConversationTurnState,
        mutation: MutationAvailability,
        session: NativeReadySession,
        expectedCursor: Int,
        submit: @escaping (NativeCommandRequest) -> Void
    ) {
        self.turn = turn
        self.mutation = mutation
        self.session = session
        self.expectedCursor = expectedCursor
        self.submit = submit
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if turn.canInterrupt {
                HStack {
                    TextField("Steer the active turn", text: $steeringText)
                        .textFieldStyle(.roundedBorder)
                        .accessibilityIdentifier("conversation-steer-field")
                    Button("Steer") { send(.steer(steeringText)) }
                        .disabled(!available(.steer(steeringText)).isEnabled)
                    Button("Interrupt") { send(.interrupt) }
                        .disabled(!available(.interrupt).isEnabled)
                }
            }
            if turn.canResume || turn.hasFailedIntent {
                HStack {
                    if turn.canResume {
                        Button("Resume") { send(.resume) }
                            .disabled(!available(.resume).isEnabled)
                    }
                    if turn.hasFailedIntent {
                        Button("Retry") { send(.retry) }
                            .disabled(!available(.retry).isEnabled)
                    }
                }
            }
            if let visibleReason {
                Text(visibleReason)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Conversation turn controls")
    }

    private func available(
        _ command: ConversationCommand
    ) -> ConversationControlAvailability {
        ConversationCommandFactory.availability(
            for: command,
            turn: turn,
            mutation: mutation,
            session: session
        )
    }

    private func send(_ command: ConversationCommand) {
        let availability = available(command)
        guard availability.isEnabled else {
            visibleReason = availability.disabledReason
            return
        }
        do {
            submit(try ConversationCommandFactory.request(
                for: command,
                expectedCursor: expectedCursor,
                session: session
            ))
            if case .steer = command { steeringText = "" }
            visibleReason = nil
        } catch {
            visibleReason = "The conversation command was refused locally."
        }
    }
}
