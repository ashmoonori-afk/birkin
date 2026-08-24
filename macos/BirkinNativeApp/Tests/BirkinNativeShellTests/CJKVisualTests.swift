import AppKit
import BirkinNativeProtocol
import SwiftUI
import Testing
@testable import BirkinNativeShell

@Suite("Korean and CJK visual fidelity")
struct CJKVisualTests {
    private let strings = [
        "로컬 Python 브리지에 연결할 수 없습니다. 진단 정보를 확인하세요.",
        "접근성 검토 세션 - 한글/日本語/漢字",
        "한국어 조합 입력을 보존하고 메시지를 명시적으로 전송합니다.",
        "목표: 접근 가능한 네이티브 여정을 완성합니다.",
        "제약: 포인터 없이 모든 작업을 완료합니다.",
    ]

    @MainActor
    @Test("CJK surfaces keep stable width and wrap without clipping at default and large text")
    func rendersDefaultAndLargeText() throws {
        let status = ConnectionStatusPill(presentation: ConnectionPresentation(
            state: .failed(reason: "로컬 Python 브리지에 연결할 수 없습니다. 진단 정보를 확인하세요.")
        ))
        try renderPair(status, name: "cjk-status-pill", size: NSSize(width: 960, height: 220))

        let menu = DesktopMenuView(
            model: DesktopMenuModel(
                connection: .failed(reason: "연결 실패"),
                sessionID: "접근성 검토 세션 - 한글/日本語/漢字",
                pendingApprovalCount: 2
            ),
            navigate: { _ in }
        )
        try renderPair(menu, name: "cjk-menu", size: NSSize(width: 960, height: 360))

        let composer = ConversationComposerModel(
            draft: "한국어 조합 입력을 보존하고 메시지를 명시적으로 전송합니다."
        )
        try renderPair(
            ConversationComposerView(model: composer, isSendEnabled: true, send: {}),
            name: "cjk-composer", size: NSSize(width: 960, height: 420)
        )

        let memory = NativeWorkingMemoryProjection(
            revision: 12,
            goal: NativeWorkingMemoryGoal(
                slug: "cjk-goal", objective: "접근 가능한 네이티브 여정을 완성합니다.",
                tokensUsed: 24, status: "active"
            ),
            fields: [
                "corrections": ["한글 조합 중에는 전송하지 않습니다."],
                "constraints": ["포인터 없이 모든 작업을 완료합니다."],
                "decisions": ["접근성 트리 순서를 유지합니다."],
                "incomplete": [], "evidence": ["日本語と漢字も切れません。"],
                "next_actions": ["최대 글자 크기 스크린샷을 검토합니다."],
            ],
            filesEvidence: [["summary": .string("문서/접근성-검토.md")]]
        )
        try renderPair(
            WorkingMemoryView(presentation: WorkingMemoryPresentation(projection: memory)),
            name: "cjk-working-memory", size: NSSize(width: 960, height: 1_000)
        )

        #expect(ShellLayoutPlan(windowWidth: 960, dynamicTypeSize: .accessibility5).mode == .panelNavigation)
        for pointSize in [13.0, 30.0] {
            for value in strings {
                let bounds = (value as NSString).boundingRect(
                    with: NSSize(width: 880, height: 180),
                    options: [.usesLineFragmentOrigin, .usesFontLeading],
                    attributes: [.font: NSFont.systemFont(ofSize: pointSize)]
                )
                #expect(bounds.width <= 880)
                #expect(bounds.height <= 180)
            }
        }
    }

    @MainActor
    private func renderPair<V: View>(_ view: V, name: String, size: NSSize) throws {
        let defaultImage = try snapshot(
            view, size: size, dynamicTypeSize: .large, named: "\(name)-default.png"
        )
        let largeImage = try snapshot(
            view, size: size, dynamicTypeSize: .accessibility5, named: "\(name)-large.png"
        )
        #expect(defaultImage.size == largeImage.size)
    }

    @MainActor
    private func snapshot<V: View>(
        _ view: V,
        size: NSSize,
        dynamicTypeSize: DynamicTypeSize,
        named: String
    ) throws -> NSImage {
        let renderer = ImageRenderer(content:
            view
                .padding(24)
                .frame(width: size.width, height: size.height, alignment: .topLeading)
                .background(Color(nsColor: .windowBackgroundColor))
                .environment(\.dynamicTypeSize, dynamicTypeSize)
                .environment(\.colorScheme, .dark)
                .environment(\.shellVisualSettings, ShellVisualSettings(snapshotRendering: true))
        )
        renderer.scale = 1
        let image = try #require(renderer.nsImage)
        #expect(image.size == size)
        let tiff = try #require(image.tiffRepresentation)
        let bitmap = try #require(NSBitmapImageRep(data: tiff))
        let png = try #require(bitmap.representation(using: .png, properties: [:]))
        #expect(png.count > 4_000)
        try png.write(to: evidenceURL(named), options: .atomic)
        return image
    }

    private func evidenceURL(_ name: String) throws -> URL {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { root.deleteLastPathComponent() }
        let directory = root.appendingPathComponent(".omo/evidence/native-shell/phase12", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory.appendingPathComponent(name)
    }
}
