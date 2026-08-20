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
}
