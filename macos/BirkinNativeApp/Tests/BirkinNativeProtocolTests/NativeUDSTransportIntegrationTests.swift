import Testing

@testable import BirkinNativeProtocol

@Suite("Real Unix-domain transport")
struct NativeUDSTransportIntegrationTests {
    @Test("Swift hello reaches ready on a live Python UDS endpoint")
    func helloReady() async throws {
        let harness = try HarnessReadiness.launch(transport: "uds")
        guard let socketPath = harness.record["socket_path"] as? String else {
            throw HarnessError.malformedReadiness
        }
        let transport = NativeTransportActor()

        let transcript = try await transport.connectUDS(
            socketPath: socketPath,
            hello: integrationHello
        )

        #expect(transcript.hello.kind == .hello)
        #expect(transcript.ready.kind == .ready)
        #expect(transcript.ready.inReplyTo == transcript.hello.id)
        #expect(transcript.transport == .uds)
        #expect(await transport.state == .ready(transcript.session))
        print("UDS TRANSCRIPT hello=\(transcript.hello.id) ready=\(transcript.ready.id) transport=uds")
        print("UDS CLEANUP \(try harness.finish()) root_removed=true")
    }

    @Test("same protocol with a different product version is refused")
    func productVersionMismatch() async throws {
        // Given a real authenticated endpoint speaking the supported protocol.
        let externalVersion = "0.0.0-mismatched"
        let harness = try HarnessReadiness.launch(
            transport: "uds",
            options: HarnessLaunchOptions(serverVersion: externalVersion)
        )
        guard let socketPath = harness.record["socket_path"] as? String else {
            throw HarnessError.malformedReadiness
        }
        let transport = NativeTransportActor()

        // When its ready frame identifies a different Birkin product version.
        do {
            _ = try await transport.connectUDS(
                socketPath: socketPath,
                hello: integrationHello
            )
            Issue.record("version-mismatched bridge became usable")
        } catch let error as NativeProductVersionError {
            // Then the exact compatibility gate rejects it independently of negotiation.
            #expect(error.expected == BirkinVersion.packageVersion)
            #expect(error.actual == externalVersion)
            #expect(error.description.count <= 160)
            #expect(await transport.state == .failed(reason: error.description))
        }
        print("VERSION MISMATCH CLEANUP \(try harness.finish()) root_removed=true")
    }
}
