import Foundation
import Testing

@testable import BirkinNativeProtocol
@testable import BirkinNativeShell

@Suite("Native shell connection presentation")
struct ConnectionPresentationTests {
    @Test("typed first-run helper failures expose reinstall guidance and Retry")
    func firstRunFailureRecovery() {
        let missing = ConnectionPresentation(state: .failed(
            reason: "code=embedded_helper_missing message=The embedded bridge executable is missing. Reinstall Birkin."
        ))
        let mismatch = ConnectionPresentation(state: .failed(
            reason: "code=embedded_helper_hash_mismatch message=The embedded bridge executable failed its integrity check. Reinstall Birkin."
        ))

        #expect(missing.identifier == "failed-embedded_helper_missing")
        #expect(mismatch.identifier == "failed-embedded_helper_hash_mismatch")
        #expect(missing.actionLabel == "Retry")
        #expect(mismatch.actionLabel == "Retry")
        #expect(missing.detail.contains("Reinstall Birkin"))
        #expect(!missing.detail.localizedCaseInsensitiveContains("choose"))
        print("B4 PRESENTATION code=embedded_helper_missing action=Retry picker=false")
    }

    @Test("every connection phase has a distinct non-color rendering")
    func everyStateIsDistinct() {
        let session = NativeReadySession(
            instanceID: "instance-1",
            serverVersion: "1.0",
            sessionCapability: "live-token"
        )
        let presentations = [
            ConnectionPresentation(state: .disconnected),
            ConnectionPresentation(state: .connecting),
            ConnectionPresentation(state: .negotiating(.uds)),
            ConnectionPresentation(state: .ready(session)),
            ConnectionPresentation(state: .fallback(.connecting(reason: "socket missing"))),
            ConnectionPresentation(state: .fallback(.negotiating)),
            ConnectionPresentation(state: .fallback(.ready(session))),
            ConnectionPresentation.reconnecting(attempt: 3, retryAfter: 4),
            ConnectionPresentation(state: .replaying(session)),
            ConnectionPresentation(state: .failed(reason: "bridge stopped")),
        ]

        #expect(Set(presentations.map(\.renderSignature)).count == presentations.count)
        #expect(presentations.allSatisfy { !$0.title.isEmpty && !$0.symbolName.isEmpty })
        #expect(presentations.allSatisfy { !$0.actionLabel.isEmpty })
    }
}
