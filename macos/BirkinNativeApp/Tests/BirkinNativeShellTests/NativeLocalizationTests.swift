import AppKit
import BirkinNativeProtocol
import Foundation
import SwiftUI
import Testing

@testable import BirkinNativeShell

@Suite("Native shell localization")
struct NativeLocalizationTests {
    private let english = Locale(identifier: "en")
    private let korean = Locale(identifier: "ko-KR")
    private let unsupported = Locale(identifier: "ja-JP")

    @Test("English is the default and unsupported locales fall back to English")
    func englishAndFallback() throws {
        #expect(
            NativeLocalization.language(for: NativeLocalization.currentLocale)
                == "en"
        )
        #expect(NativeLocalization.language(for: english) == "en")
        #expect(NativeLocalization.language(for: unsupported) == "en")
        #expect(
            NativeLocalization.string("Commands", locale: english)
                == "Commands"
        )
        #expect(
            NativeLocalization.string("Commands", locale: unsupported)
                == "Commands"
        )
        #expect(try #require(
            NativeLocalization.resourceURL(language: "en")
        ).isFileURL)
        #expect(try #require(
            NativeLocalization.resourceURL(language: "ko")
        ).isFileURL)
    }

    @Test("Korean chrome preserves CJK authority values")
    func koreanChromePreservesAuthorityValues() {
        let reason = "/tmp/권한.sock · E_PROTOCOL · 日本語"
        let status = ConnectionPresentation(
            state: .fallback(.connecting(reason: reason)),
            locale: korean
        )
        let menu = DesktopMenuModel(
            connection: .connectedSession,
            sessionID: "세션-日本語",
            pendingApprovalCount: 2,
            locale: korean
        )

        #expect(status.title == "연결 중")
        #expect(status.detail.contains(reason))
        #expect(status.actionLabel == "진단 보기")
        #expect(menu.connectionTitle == "연결됨")
        #expect(menu.items.map(\.title) == [
            "연결: 연결됨",
            "세션: 세션-日本語",
            "승인 (2)",
        ])
        #expect(
            NativeLocalization.string(
                "Show Navigation Panel",
                locale: korean
            ) == "탐색 패널 보기"
        )
        #expect(
            NativeLocalization.string(
                "Show Conversation Panel",
                locale: korean
            ) == "대화 패널 보기"
        )
        #expect(
            NativeLocalization.string(
                "Show Context Panel",
                locale: korean
            ) == "컨텍스트 패널 보기"
        )
        #expect(
            NativeLocalization.string(
                "Drop a file to import",
                locale: korean
            ) == "가져올 파일을 놓으세요"
        )
        #expect(
            NativeLocalization.string("Hide read", locale: korean)
                == "읽은 항목 숨기기"
        )
        #expect(
            NativeLocalization.string("Send", locale: korean)
                == "보내기"
        )
        #expect(
            NativeLocalization.string(
                "%lld bytes",
                locale: korean,
                Int64(11)
            ) == "11바이트"
        )
    }

    @Test("localized VoiceOver nodes preserve semantics and identifiers")
    func voiceOverSemantics() throws {
        let englishNodes = try #require(ShellVoiceOverModel.journey(
            .j2ResearchApproval,
            locale: english
        ))
        let koreanNodes = try #require(ShellVoiceOverModel.journey(
            .j2ResearchApproval,
            locale: korean
        ))

        #expect(koreanNodes.map(\.id) == englishNodes.map(\.id))
        #expect(koreanNodes.map(\.role) == englishNodes.map(\.role))
        #expect(
            koreanNodes.map(\.sortPriority)
                == englishNodes.map(\.sortPriority)
        )
        #expect(koreanNodes[3].value == "위험, 범주 및 요약")
        #expect(
            koreanNodes.filter { $0.role == .button }
                .allSatisfy { $0.actions == ["press"] }
        )
        #expect(koreanNodes.allSatisfy { !$0.label.isEmpty })
    }

    @MainActor
    @Test("Korean CJK chrome renders at largest accessibility text")
    func koreanLargeTextRendering() throws {
        let status = ConnectionStatusPill(
            presentation: ConnectionPresentation(
                state: .fallback(.connecting(
                    reason: "로컬 경로 /tmp/日本語.sock"
                )),
                locale: korean
            )
        )
        let menu = DesktopMenuView(
            model: DesktopMenuModel(
                connection: .disconnected,
                sessionID: "접근성-日本語-漢字",
                pendingApprovalCount: 3,
                locale: korean
            ),
            navigate: { _ in }
        )
        let view = VStack(alignment: .leading) {
            status
            menu
        }
        .padding(24)
        .environment(\.dynamicTypeSize, .accessibility5)
        .frame(width: 960, height: 520, alignment: .topLeading)
        let renderer = ImageRenderer(content: view)
        renderer.scale = 1
        let image = try #require(renderer.nsImage)
        let bitmap = try #require(
            image.tiffRepresentation.flatMap(NSBitmapImageRep.init)
        )
        let png = try #require(
            bitmap.representation(using: .png, properties: [:])
        )

        #expect(image.size == NSSize(width: 960, height: 520))
        #expect(png.count > 4_000)
    }
}

private extension NativeConnectionState {
    static var connectedSession: NativeConnectionState {
        .ready(NativeReadySession(
            instanceID: "instance-1",
            serverVersion: "1.0",
            sessionCapability: "token"
        ))
    }
}
