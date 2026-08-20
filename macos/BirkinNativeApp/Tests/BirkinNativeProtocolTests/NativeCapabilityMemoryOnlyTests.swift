import Foundation
import Testing

@testable import BirkinNativeProtocol

@Suite("Native capability lifetime")
struct NativeCapabilityMemoryOnlyTests {
    @Test("bootstrap and session capabilities remain memory-only after fallback")
    func noCapabilityPersistence() async throws {
        let harness = try HarnessReadiness.launch(transport: "loopback")
        guard let discoveryPath = harness.record["discovery_path"] as? String else {
            throw HarnessError.malformedReadiness
        }
        let discoveryData = try Data(contentsOf: URL(fileURLWithPath: discoveryPath))
        guard let discovery = try JSONSerialization.jsonObject(with: discoveryData) as? [String: Any],
              let bootstrapSecret = discovery["bootstrap_secret"] as? String
        else {
            throw HarnessError.malformedReadiness
        }
        let swiftTemp = URL(
            fileURLWithPath: "/private/tmp/birkin-swift-memory-\(UUID().uuidString)"
        )
        try FileManager.default.createDirectory(at: swiftTemp, withIntermediateDirectories: true)

        let transport = NativeTransportActor()
        let transcript = try await transport.connectWithFallback(
            udsSocketPath: harness.root.appendingPathComponent("unavailable.sock").path,
            discoveryPath: discoveryPath,
            hello: integrationHello
        )
        let receipt = try harness.finish(removeRoot: false)

        let leakedFiles = try filesContaining(
            [Data(bootstrapSecret.utf8), Data(transcript.session.sessionCapability.utf8)],
            beneath: [harness.root, swiftTemp]
        )

        #expect(leakedFiles.isEmpty)
        print("MEMORY-ONLY SCAN matches=\(leakedFiles.map(\.path).sorted())")
        try FileManager.default.removeItem(at: harness.root)
        try FileManager.default.removeItem(at: swiftTemp)
        print("MEMORY-ONLY CLEANUP \(receipt) roots_removed=true")
    }

    private func filesContaining(_ needles: [Data], beneath roots: [URL]) throws -> [URL] {
        var matches: [URL] = []
        for root in roots {
            guard let enumerator = FileManager.default.enumerator(
                at: root,
                includingPropertiesForKeys: [.isRegularFileKey],
                options: [.skipsHiddenFiles]
            ) else { continue }
            for case let file as URL in enumerator {
                let values = try file.resourceValues(forKeys: [.isRegularFileKey])
                guard values.isRegularFile == true else { continue }
                let contents = try Data(contentsOf: file)
                if needles.contains(where: { contents.range(of: $0) != nil }) {
                    matches.append(file)
                }
            }
        }
        return matches
    }
}
