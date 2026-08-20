import Foundation
import Testing

@testable import BirkinNativeProtocol
@testable import BirkinNativeShell

@Suite("Native shell connection presentation")
struct ConnectionPresentationTests {
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
        #expect(presentations.allSatisfy { $0.diagnosticsLabel == "Show Diagnostics" })
    }
}
