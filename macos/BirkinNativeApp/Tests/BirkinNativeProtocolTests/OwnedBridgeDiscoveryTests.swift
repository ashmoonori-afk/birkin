import CryptoKit
import Foundation
import Testing

@testable import BirkinNativeProtocol

@Suite("Embedded bridge helper discovery")
struct OwnedBridgeDiscoveryTests {
    @Test("a valid helper for the running architecture is selected")
    func validEmbeddedHelper() throws {
        // Given a bundle with a same-version manifest and matching helper hash.
        let fixture = try EmbeddedHelperFixture()
        defer { fixture.remove() }
        try fixture.writeManifest()

        // When production discovery runs without a developer override.
        let configuration = try #require(OwnedBridgeConfiguration.discovered(
            in: [:],
            bundleURL: fixture.bundleURL
        ))

        // Then it selects only the helper for this executable architecture.
        #expect(configuration.executable == fixture.helperURL.path)
        #expect(configuration.leadingArguments.isEmpty)
        #expect(OwnedBridgeConfiguration.discoveryFailure(
            in: [:],
            bundleURL: fixture.bundleURL
        ) == nil)
    }

    @Test("developer override remains discoverable without an embedded manifest")
    func developerOverride() throws {
        // Given an explicit developer command and no packaged helper.
        let bundleURL = URL(fileURLWithPath: "/missing/Birkin.app")
        let environment = [
            OwnedBridgeConfiguration.commandEnvironmentKey: "/developer/python",
            OwnedBridgeConfiguration.argumentsEnvironmentKey: "-m birkin",
        ]

        // When discovery resolves the installation.
        let configuration = try #require(OwnedBridgeConfiguration.discovered(
            in: environment,
            bundleURL: bundleURL
        ))

        // Then override discovery remains available for the independently gated handshake.
        #expect(configuration.executable == "/developer/python")
        #expect(configuration.leadingArguments == ["-m", "birkin"])
        #expect(OwnedBridgeConfiguration.discoveryFailure(
            in: environment,
            bundleURL: bundleURL
        ) == nil)
    }

    @Test("missing embedded manifest fails with a bounded remediation code")
    func missingManifest() throws {
        // Given an application bundle with no helper manifest.
        let fixture = try EmbeddedHelperFixture()
        defer { fixture.remove() }

        // When discovery diagnoses the embedded installation.
        let failure = try #require(OwnedBridgeConfiguration.discoveryFailure(
            in: [:],
            bundleURL: fixture.bundleURL
        ))

        // Then it fails closed with a stable bounded diagnostic.
        #expect(failure.code == .manifestMissing)
        #expect(failure.description.count <= 160)
        #expect(OwnedBridgeConfiguration.discoveryDiagnostic(
            in: [:],
            bundleURL: fixture.bundleURL
        ).count <= 160)
        #expect(OwnedBridgeConfiguration.discovered(
            in: [:],
            bundleURL: fixture.bundleURL
        ) == nil)
    }

    @Test("tampered embedded helper fails before launch")
    func tamperedHelper() throws {
        // Given a manifest sealed to the original helper bytes.
        let fixture = try EmbeddedHelperFixture()
        defer { fixture.remove() }
        try fixture.writeManifest()
        try Data("tampered".utf8).write(to: fixture.helperURL)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o755],
            ofItemAtPath: fixture.helperURL.path
        )

        // When discovery verifies the helper.
        let failure = try #require(OwnedBridgeConfiguration.discoveryFailure(
            in: [:],
            bundleURL: fixture.bundleURL
        ))

        // Then changed bytes are rejected with no executable configuration.
        #expect(failure.code == .helperHashMismatch)
        #expect(failure.description.count <= 160)
        #expect(OwnedBridgeConfiguration.discovered(
            in: [:],
            bundleURL: fixture.bundleURL
        ) == nil)
    }

    @Test("symbolic-link helper fails before launch")
    func symbolicLinkHelper() throws {
        // Given a matching helper manifest whose executable is later replaced by a symlink.
        let fixture = try EmbeddedHelperFixture()
        defer { fixture.remove() }
        try fixture.writeManifest()
        let target = fixture.root.appendingPathComponent("external-helper")
        try Data("embedded-helper".utf8).write(to: target)
        try FileManager.default.removeItem(at: fixture.helperURL)
        try FileManager.default.createSymbolicLink(
            at: fixture.helperURL,
            withDestinationURL: target
        )

        // When discovery checks the executable file type.
        let failure = try #require(OwnedBridgeConfiguration.discoveryFailure(
            in: [:],
            bundleURL: fixture.bundleURL
        ))

        // Then a same-hash path substitution is still rejected.
        #expect(failure.code == .helperInvalid)
    }

    @Test("manifest without the running architecture fails closed")
    func missingArchitecture() throws {
        // Given a manifest containing only another helper architecture.
        let fixture = try EmbeddedHelperFixture()
        defer { fixture.remove() }
        try fixture.writeManifest(architecture: "unsupported")

        // When discovery resolves the executable architecture.
        let failure = try #require(OwnedBridgeConfiguration.discoveryFailure(
            in: [:],
            bundleURL: fixture.bundleURL
        ))

        // Then no other architecture is selected as a fallback.
        #expect(failure.code == .architectureMissing)
    }

    @Test("dirty embedded helper revision fails closed")
    func dirtySourceRevision() throws {
        // Given a helper manifest produced from uncommitted source.
        let fixture = try EmbeddedHelperFixture()
        defer { fixture.remove() }
        try fixture.writeManifest(sourceState: "dirty")

        // When discovery checks the revision state.
        let failure = try #require(OwnedBridgeConfiguration.discoveryFailure(
            in: [:],
            bundleURL: fixture.bundleURL
        ))

        // Then the helper cannot become the application authority.
        #expect(failure.code == .manifestSourceDirty)
        #expect(failure.description.count <= 160)
    }

    @Test("embedded manifest from another product version fails closed")
    func manifestVersionMismatch() throws {
        // Given a well-formed helper manifest from another Birkin version.
        let fixture = try EmbeddedHelperFixture()
        defer { fixture.remove() }
        try fixture.writeManifest(version: "0.0.0-mismatched")

        // When discovery checks package compatibility.
        let failure = try #require(OwnedBridgeConfiguration.discoveryFailure(
            in: [:],
            bundleURL: fixture.bundleURL
        ))

        // Then product identity is rejected before process launch.
        #expect(failure.code == .manifestVersionMismatch)
        #expect(failure.description.count <= 160)
    }
}

private struct EmbeddedHelperFixture {
    let root: URL
    let bundleURL: URL
    let helperURL: URL

    init() throws {
        root = URL(fileURLWithPath: "/private/tmp/bk-helper-\(UUID().uuidString)")
        bundleURL = root.appendingPathComponent("Birkin.app")
        helperURL = bundleURL
            .appendingPathComponent("Contents/Helpers")
            .appendingPathComponent(OwnedBridgeConfiguration.currentArchitecture)
            .appendingPathComponent("birkin-native-bridge")
        try FileManager.default.createDirectory(
            at: helperURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try Data("embedded-helper".utf8).write(to: helperURL)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o755],
            ofItemAtPath: helperURL.path
        )
    }

    func writeManifest(
        version: String = BirkinVersion.packageVersion,
        sourceState: String = "clean",
        architecture: String = OwnedBridgeConfiguration.currentArchitecture
    ) throws {
        let helperHash = SHA256.hash(data: try Data(contentsOf: helperURL))
            .map { String(format: "%02x", $0) }
            .joined()
        let record: [String: Any] = [
            "schema": 1,
            "package_version": version,
            "source_revision": String(repeating: "0", count: 40),
            "source_state": sourceState,
            "python_version": "3.13.13",
            "python_build": "20260414",
            "dependency_lock_sha256": String(repeating: "1", count: 64),
            "build_lock_sha256": String(repeating: "2", count: 64),
            "inputs_sha256": String(repeating: "3", count: 64),
            "helpers": [[
                "architecture": architecture,
                "path": "\(architecture)/birkin-native-bridge",
                "sha256": helperHash,
            ]],
        ]
        let data = try JSONSerialization.data(withJSONObject: record, options: [.sortedKeys])
        let manifestURL = bundleURL
            .appendingPathComponent("Contents/Resources")
            .appendingPathComponent(OwnedBridgeConfiguration.manifestFilename)
        try FileManager.default.createDirectory(
            at: manifestURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try data.write(to: manifestURL)
    }

    func remove() {
        try? FileManager.default.removeItem(at: root)
    }
}
