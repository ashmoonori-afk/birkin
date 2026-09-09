import SwiftUI

public struct WorkingMemoryClearPresentation: Equatable, Sendable {
    public let title: String
    public let explanation: String
    public let confirmAccessibilityLabel: String

    public init(sessionID: String) {
        title = "\(sessionID) 업무의 작업 기억을 비울까요?"
        explanation = "이 업무의 수정 사항, 제약 조건, 결정, 미완료 항목, 근거와 다음 작업을 비웁니다. 장기 기억, 작업공간 파일과 감사 기록은 지우지 않습니다."
        confirmAccessibilityLabel = "이 업무의 작업 기억만 비우기"
    }
}

struct WorkingMemoryClearConfirmationView: View {
    let presentation: WorkingMemoryClearPresentation

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(presentation.title).font(.headline)
            Text(presentation.explanation)
            Button("비우기") {}
                .accessibilityLabel(presentation.confirmAccessibilityLabel)
        }
        .padding(24)
    }
}

public struct WorkingMemoryCanonicalErrorPresentation: Equatable, Sendable {
    public let code: String
    public let message: String
    public let accessibilityLabel: String

    public init(code: String, message: String) {
        self.code = code
        self.message = String(message.prefix(300))
        switch code {
        case "E_WORKING_MEMORY_BUDGET":
            accessibilityLabel = "작업 기억이 20,000자 표시 제한을 넘었습니다. 내용을 줄인 뒤 다시 시도하세요."
        case "E_WORKING_MEMORY_REVISION":
            accessibilityLabel = "작업 기억 버전이 달라졌습니다. 최신 상태를 확인한 뒤 다시 시도하세요."
        default:
            accessibilityLabel = "작업 기억을 업데이트하지 못했습니다. \(String(message.prefix(200)))"
        }
    }
}

struct WorkingMemoryCanonicalErrorView: View {
    let presentation: WorkingMemoryCanonicalErrorPresentation

    var body: some View {
        Label(presentation.message, systemImage: "exclamationmark.triangle")
            .foregroundStyle(.red)
            .accessibilityLabel(presentation.accessibilityLabel)
            .padding(24)
    }
}
