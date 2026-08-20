import Foundation
import Testing

@testable import BirkinNativeProtocol

@Suite("Projection persistence boundary")
struct NativeProjectionPersistenceTests {
    @Test("projection authority remains ephemeral and persistence-free")
    func projectionNeverPersists() throws {
        let sandbox = FileManager.default.temporaryDirectory
            .appendingPathComponent("birkin-projection-scan-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: sandbox, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: sandbox) }

        let vectors = try ProjectionVectors.load()
        let store = NativeProjectionStore()
        try store.apply(snapshot: vectors.snapshot)

        let persistedMatches = try filesContainingProjectionData(beneath: sandbox)
        let forbiddenSourceMatches = try projectionSourcesUsingPersistence()

        #expect(persistedMatches.isEmpty)
        #expect(forbiddenSourceMatches.isEmpty)
        print("PROJECTION-PERSISTENCE SCAN data_matches=\(persistedMatches.sorted()) "
            + "source_matches=\(forbiddenSourceMatches.sorted())")
        try FileManager.default.removeItem(at: sandbox)
        print("PROJECTION-PERSISTENCE CLEANUP root=\(sandbox.path) removed=true")
    }

    private func filesContainingProjectionData(beneath root: URL) throws -> [String] {
        let markers = [Data("session-1".utf8), Data("Ship the reducer".utf8)]
        guard let enumerator = FileManager.default.enumerator(
            at: root,
            includingPropertiesForKeys: [.isRegularFileKey]
        ) else { return [] }
        var matches: [String] = []
        for case let file as URL in enumerator {
            guard try file.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile == true else {
                continue
            }
            let contents = try Data(contentsOf: file)
            if markers.contains(where: { contents.range(of: $0) != nil }) {
                matches.append(file.path)
            }
        }
        return matches
    }

    private func projectionSourcesUsingPersistence() throws -> [String] {
        let packageRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let sourceRoot = packageRoot
            .appendingPathComponent("Sources/BirkinNativeProtocol")
        let forbidden = [
            "CoreData", "SwiftData", "SQLite", "UserDefaults",
            "Application Support", "FileManager", "Data.write",
        ]
        let files = try FileManager.default.contentsOfDirectory(
            at: sourceRoot,
            includingPropertiesForKeys: nil
        ).filter { $0.lastPathComponent.hasPrefix("NativeProjection") }
        return try files.flatMap { file -> [String] in
            let source = try String(contentsOf: file, encoding: .utf8)
            return forbidden.compactMap { token in
                source.contains(token) ? "\(file.lastPathComponent):\(token)" : nil
            }
        }
    }
}
