import Testing

@testable import BirkinNativeProtocol

@Suite("Real loopback fallback transport")
struct NativeLoopbackTransportIntegrationTests {
    @Test("missing UDS falls back through discovery and authenticates")
    func authenticatedFallback() async throws {
        let harness = try HarnessReadiness.launch(transport: "loopback")
        guard let discoveryPath = harness.record["discovery_path"] as? String else {
            throw HarnessError.malformedReadiness
        }
        let transport = NativeTransportActor()

        let transcript = try await transport.connectWithFallback(
            udsSocketPath: harness.root.appendingPathComponent("unavailable.sock").path,
            discoveryPath: discoveryPath,
            hello: integrationHello
        )

        #expect(transcript.hello.kind == .hello)
        #expect(transcript.ready.kind == .ready)
        #expect(transcript.transport == .loopback)
        #expect(await transport.state == .fallback(.ready(transcript.session)))
        #expect(transcript.ready.inReplyTo == transcript.hello.id)
        print(
            "FALLBACK TRANSCRIPT hello=\(transcript.hello.id) "
                + "ready=\(transcript.ready.id) transport=loopback state=fallback.ready"
        )
        print("FALLBACK CLEANUP \(try harness.finish()) root_removed=true")
    }
}
