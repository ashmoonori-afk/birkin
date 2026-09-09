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
                    TextField("진행 중인 응답에 추가 지시", text: $steeringText)
                        .textFieldStyle(.roundedBorder)
                        .accessibilityIdentifier("conversation-steer-field")
                    Button("지시 보내기") { send(.steer(steeringText)) }
                        .disabled(!available(.steer(steeringText)).isEnabled)
                    Button("중지") { send(.interrupt) }
                        .disabled(!available(.interrupt).isEnabled)
                }
            }
            if turn.canResume || turn.hasFailedIntent {
                HStack {
                    if turn.canResume {
                        Button("계속") { send(.resume) }
                            .disabled(!available(.resume).isEnabled)
                    }
                    if turn.hasFailedIntent {
                        Button("다시 시도") { send(.retry) }
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
        .accessibilityLabel("대화 응답 제어")
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
            visibleReason = "이 기기에서 대화 명령을 처리하지 못했습니다. 연결 상태를 확인하고 다시 시도하세요."
        }
    }
}
