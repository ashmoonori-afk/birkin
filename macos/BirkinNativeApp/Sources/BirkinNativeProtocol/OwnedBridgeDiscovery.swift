import CryptoKit
import Foundation

private struct BridgeHelperManifest: Decodable {
    let schema: Int
    let packageVersion: String
    let sourceRevision: String
    let sourceState: String
    let pythonVersion: String
    let pythonBuild: String
    let dependencyLockSHA256: String
    let buildLockSHA256: String
    let inputsSHA256: String
    let helpers: [BridgeHelperRecord]

    enum CodingKeys: String, CodingKey {
        case schema, helpers
        case packageVersion = "package_version"
        case sourceRevision = "source_revision"
        case sourceState = "source_state"
        case pythonVersion = "python_version"
        case pythonBuild = "python_build"
        case dependencyLockSHA256 = "dependency_lock_sha256"
        case buildLockSHA256 = "build_lock_sha256"
        case inputsSHA256 = "inputs_sha256"
    }
}

private struct BridgeHelperRecord: Decodable {
    let architecture: String
    let path: String
    let sha256: String
}

extension OwnedBridgeConfiguration {
    public static let manifestFilename = "bridge-helper.json"

    #if arch(arm64)
    public static let currentArchitecture = "arm64"
    #elseif arch(x86_64)
    public static let currentArchitecture = "x86_64"
    #else
    public static let currentArchitecture = "unsupported"
    #endif

    /// The developer override or verified helper this installation provides.
    public static func discovered(
        in environment: [String: String] = ProcessInfo.processInfo.environment,
        bundleURL: URL = Bundle.main.bundleURL
    ) -> OwnedBridgeConfiguration? {
        switch resolve(in: environment, bundleURL: bundleURL) {
        case .success(let configuration): configuration
        case .failure: nil
        }
    }

    /// Why discovery failed, or nil when an override/helper is usable.
    public static func discoveryFailure(
        in environment: [String: String] = ProcessInfo.processInfo.environment,
        bundleURL: URL = Bundle.main.bundleURL
    ) -> OwnedBridgeDiscoveryError? {
        switch resolve(in: environment, bundleURL: bundleURL) {
        case .success: nil
        case .failure(let error): error
        }
    }

    /// A stable event fragment for an installation that cannot start a helper.
    public static func discoveryDiagnostic(
        in environment: [String: String] = ProcessInfo.processInfo.environment,
        bundleURL: URL = Bundle.main.bundleURL
    ) -> String {
        guard let error = discoveryFailure(in: environment, bundleURL: bundleURL) else {
            return "code=embedded_helper_unavailable"
        }
        return "code=\(error.code.rawValue) message=\(error.description)"
    }

    private static func resolve(
        in environment: [String: String],
        bundleURL: URL
    ) -> Result<OwnedBridgeConfiguration, OwnedBridgeDiscoveryError> {
        if let command = environment[commandEnvironmentKey], !command.isEmpty {
            let arguments = environment[argumentsEnvironmentKey]?
                .split(separator: " ").map(String.init) ?? []
            let options = environment[optionsEnvironmentKey]?
                .split(separator: " ").map(String.init) ?? []
            return .success(OwnedBridgeConfiguration(
                executable: command,
                leadingArguments: arguments,
                serveOptions: options
            ))
        }
        do {
            return .success(try embeddedConfiguration(bundleURL: bundleURL))
        } catch let error as OwnedBridgeDiscoveryError {
            return .failure(error)
        } catch {
            return .failure(OwnedBridgeDiscoveryError(.manifestMalformed))
        }
    }

    private static func embeddedConfiguration(
        bundleURL: URL
    ) throws -> OwnedBridgeConfiguration {
        let helpersRoot = bundleURL.appendingPathComponent("Contents/Helpers")
        let manifestURL = bundleURL
            .appendingPathComponent("Contents/Resources")
            .appendingPathComponent(manifestFilename)
        guard FileManager.default.fileExists(atPath: manifestURL.path) else {
            throw OwnedBridgeDiscoveryError(.manifestMissing)
        }
        let manifest: BridgeHelperManifest
        do {
            manifest = try JSONDecoder().decode(
                BridgeHelperManifest.self,
                from: Data(contentsOf: manifestURL)
            )
        } catch {
            throw OwnedBridgeDiscoveryError(.manifestMalformed)
        }
        guard manifest.sourceState == "clean" else {
            throw OwnedBridgeDiscoveryError(.manifestSourceDirty)
        }
        guard manifest.schema == 1,
              manifest.packageVersion == BirkinVersion.packageVersion,
              validHex(manifest.sourceRevision, count: 40),
              !manifest.pythonVersion.isEmpty,
              !manifest.pythonBuild.isEmpty,
              validHex(manifest.dependencyLockSHA256, count: 64),
              validHex(manifest.buildLockSHA256, count: 64),
              validHex(manifest.inputsSHA256, count: 64) else {
            if manifest.packageVersion != BirkinVersion.packageVersion {
                throw OwnedBridgeDiscoveryError(.manifestVersionMismatch)
            }
            throw OwnedBridgeDiscoveryError(.manifestMalformed)
        }
        let records = manifest.helpers.filter { $0.architecture == currentArchitecture }
        guard records.count == 1, let record = records.first else {
            throw OwnedBridgeDiscoveryError(.architectureMissing)
        }
        let expectedPath = "\(currentArchitecture)/birkin-native-bridge"
        guard record.path == expectedPath, validHex(record.sha256, count: 64) else {
            throw OwnedBridgeDiscoveryError(.manifestMalformed)
        }
        let helperURL = helpersRoot.appendingPathComponent(record.path)
        guard FileManager.default.fileExists(atPath: helperURL.path) else {
            throw OwnedBridgeDiscoveryError(.helperMissing)
        }
        let values = try helperURL.resourceValues(
            forKeys: [.isRegularFileKey, .isSymbolicLinkKey]
        )
        guard values.isRegularFile == true,
              values.isSymbolicLink != true,
              FileManager.default.isExecutableFile(atPath: helperURL.path) else {
            throw OwnedBridgeDiscoveryError(.helperInvalid)
        }
        let digest = SHA256.hash(data: try Data(contentsOf: helperURL))
            .map { String(format: "%02x", $0) }
            .joined()
        guard digest == record.sha256 else {
            throw OwnedBridgeDiscoveryError(.helperHashMismatch)
        }
        return OwnedBridgeConfiguration(executable: helperURL.path)
    }

    private static func validHex(_ value: String, count: Int) -> Bool {
        value.count == count && value.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }
    }
}
