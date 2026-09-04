import CryptoKit
import Foundation

/// How to start the Python bridge this application owns.
///
/// The application never decides bridge policy: it only locates the shipped
/// command and asks it to serve. Every argument beyond the fixed
/// `native-bridge serve` verb comes from the installation, not from Swift.
public struct OwnedBridgeConfiguration: Equatable, Sendable {
    public static let commandEnvironmentKey = "BIRKIN_NATIVE_BRIDGE_COMMAND"
    public static let argumentsEnvironmentKey = "BIRKIN_NATIVE_BRIDGE_ARGUMENTS"
    public static let optionsEnvironmentKey = "BIRKIN_NATIVE_BRIDGE_OPTIONS"

    public let executable: String
    public let leadingArguments: [String]
    public let serveOptions: [String]
    public let readinessTimeout: TimeInterval
    public let transport: NativeTransportKind

    public init(
        executable: String,
        leadingArguments: [String] = [],
        serveOptions: [String] = [],
        readinessTimeout: TimeInterval = 30,
        transport: NativeTransportKind = .uds
    ) {
        self.executable = executable
        self.leadingArguments = leadingArguments
        self.serveOptions = serveOptions
        self.readinessTimeout = readinessTimeout
        self.transport = transport
    }

    var argumentList: [String] {
        leadingArguments + ["native-bridge", "serve", "--transport", transport.rawValue] + serveOptions
    }

    public func selectingTransport(_ transport: NativeTransportKind) -> Self {
        Self(
            executable: executable,
            leadingArguments: leadingArguments,
            serveOptions: serveOptions,
            readinessTimeout: readinessTimeout,
            transport: transport
        )
    }

    var ownershipRoot: URL? {
        guard let index = serveOptions.firstIndex(of: "--root"),
              serveOptions.indices.contains(index + 1) else { return nil }
        return URL(fileURLWithPath: serveOptions[index + 1])
    }
}

public enum OwnedBridgeLaunchError: Error, Equatable {
    case readinessTimedOut
    case malformedReadiness
    case readinessIdentityMismatch
}

/// One live bridge process this application started.
public struct LaunchedBridge {
    public let process: any SupervisedBridgeProcess
    public let endpointPath: String
    public let transport: NativeTransportKind
    public let instanceID: String?

    public var socketPath: String { endpointPath }
}

/// Starts the shipped bridge command and waits for it to announce its endpoint.
public enum OwnedBridgeLauncher {
    public static func launch(
        _ configuration: OwnedBridgeConfiguration,
        onExit: @escaping @Sendable (Int32, Int32) -> Void
    ) throws -> LaunchedBridge {
        let process = Process()
        let output = Pipe()
        let drain = BridgeOutputDrain(handle: output.fileHandleForReading)
        process.executableURL = URL(fileURLWithPath: configuration.executable)
        process.arguments = configuration.argumentList
        process.standardOutput = output
        process.standardError = FileHandle.standardError
        if let token = try ownershipToken(for: configuration) {
            process.environment = ProcessInfo.processInfo.environment.merging(
                ["BIRKIN_NATIVE_OWNER_TOKEN": token],
                uniquingKeysWith: { _, owned in owned }
            )
        }
        process.terminationHandler = { finished in
            drain.close()
            onExit(finished.processIdentifier, finished.terminationStatus)
        }
        drain.start()
        do {
            try process.run()
            let readiness = try drain.readiness(timeout: configuration.readinessTimeout)
            // A readiness line is data, not signal authority. Foundation's Process
            // object is the only stable identity this launcher owns, so a helper
            // that announces any other PID is rejected and only that Process is
            // ever terminated.
            guard readiness.pid == process.processIdentifier else {
                throw OwnedBridgeLaunchError.readinessIdentityMismatch
            }
            return LaunchedBridge(
                process: FoundationBridgeProcess(process: process, outputDrain: drain),
                endpointPath: readiness.endpointPath,
                transport: readiness.transport,
                instanceID: nil
            )
        } catch {
            if process.isRunning { process.terminate() }
            drain.close()
            throw error
        }
    }

    /// Authenticates and renews a surviving helper claim without acquiring PID
    /// signal authority. The subsequent protocol handshake must still match
    /// `instanceID` before the caller treats this endpoint as ready.
    public static func reclaim(
        _ configuration: OwnedBridgeConfiguration
    ) throws -> LaunchedBridge? {
        guard let root = configuration.ownershipRoot,
              let token = try ownershipToken(for: configuration) else { return nil }
        let recordURL = root.appendingPathComponent("native/ownership.json")
        guard let data = try? Data(contentsOf: recordURL),
              let record = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              record["schema"] as? Int == 1,
              let instanceID = record["instance_id"] as? String,
              let rawPID = record["pid"] as? Int,
              rawPID > 0, rawPID <= Int(Int32.max),
              record["transport"] as? String == "uds",
              let socketPath = record["endpoint"] as? String,
              !socketPath.isEmpty,
              let expectedDigest = record["owner_token_sha256"] as? String,
              expectedDigest == sha256(token),
              let leaseExpiry = record["lease_expires_at"] as? Double,
              leaseExpiry > Date().timeIntervalSince1970,
              kill(Int32(rawPID), 0) == 0 else { return nil }
        let ownerID = UUID().uuidString.lowercased()
        let expiresAt = Date().timeIntervalSince1970 + 8
        let payload = "\(instanceID)\n\(ownerID)\n\(String(format: "%.6f", expiresAt))"
        let key = SymmetricKey(data: Data(token.utf8))
        let signature = HMAC<SHA256>.authenticationCode(
            for: Data(payload.utf8), using: key
        ).map { String(format: "%02x", $0) }.joined()
        let claim = try JSONSerialization.data(withJSONObject: [
            "instance_id": instanceID,
            "owner_id": ownerID,
            "expires_at": expiresAt,
            "signature": signature,
        ], options: [.sortedKeys])
        let claimURL = root.appendingPathComponent("native/ownership.claim")
        try claim.write(to: claimURL, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: claimURL.path)
        return LaunchedBridge(
            process: ClaimedBridgeProcess(pid: Int32(rawPID), claimURL: claimURL),
            endpointPath: socketPath,
            transport: .uds,
            instanceID: instanceID
        )
    }

    private static func ownershipToken(
        for configuration: OwnedBridgeConfiguration
    ) throws -> String? {
        guard let root = configuration.ownershipRoot else { return nil }
        let directory = root.appendingPathComponent("native")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let url = directory.appendingPathComponent("owner-token")
        if let token = try? String(contentsOf: url, encoding: .utf8), !token.isEmpty {
            return token
        }
        let token = (0..<32).map { _ in String(format: "%02x", UInt8.random(in: 0...255)) }.joined()
        try Data(token.utf8).write(to: url, options: .withoutOverwriting)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
        return token
    }

    private static func sha256(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

private final class ClaimedBridgeProcess: SupervisedBridgeProcess {
    let pid: Int32
    private let claimURL: URL

    init(pid: Int32, claimURL: URL) {
        self.pid = pid
        self.claimURL = claimURL
    }

    func terminate() {
        // Closing the authenticated protocol connection starts the helper's
        // bounded self-retirement. A reclaimed PID is never signalled.
        try? FileManager.default.removeItem(at: claimURL)
    }
}

private struct BridgeReadiness: Sendable {
    let endpointPath: String
    let transport: NativeTransportKind
    let pid: Int32
}

/// Reads exactly one bounded control line, then privately discards all later
/// diagnostics for the process lifetime. No diagnostic bytes are retained or
/// copied into application logging.
private final class BridgeOutputDrain: @unchecked Sendable {
    private static let maximumReadinessBytes = 16 * 1024

    private let handle: FileHandle
    private let lock = NSLock()
    private let ready = DispatchSemaphore(value: 0)
    private var result: Result<BridgeReadiness, OwnedBridgeLaunchError>?
    private var closed = false

    init(handle: FileHandle) { self.handle = handle }

    func start() {
        Thread.detachNewThread { [self] in
            var line = Data()
            var announced = false
            while true {
                let chunk = handle.availableData
                if chunk.isEmpty {
                    publish(.failure(.malformedReadiness))
                    return
                }
                guard !announced else { continue }
                if let newline = chunk.firstIndex(of: 0x0a) {
                    line.append(chunk.prefix(upTo: newline))
                    announced = true
                    publish(Self.parse(line))
                    continue
                }
                line.append(chunk)
                if line.count > Self.maximumReadinessBytes {
                    announced = true
                    publish(.failure(.malformedReadiness))
                }
            }
        }
    }

    func readiness(timeout: TimeInterval) throws -> BridgeReadiness {
        guard ready.wait(timeout: .now() + timeout) == .success else {
            throw OwnedBridgeLaunchError.readinessTimedOut
        }
        return try lock.withLock {
            try result?.get() ?? { throw OwnedBridgeLaunchError.malformedReadiness }()
        }
    }

    func close() {
        let shouldClose = lock.withLock { () -> Bool in
            guard !closed else { return false }
            closed = true
            return true
        }
        if shouldClose { try? handle.close() }
    }

    private func publish(_ value: Result<BridgeReadiness, OwnedBridgeLaunchError>) {
        let shouldSignal = lock.withLock { () -> Bool in
            guard result == nil else { return false }
            result = value
            return true
        }
        if shouldSignal { ready.signal() }
    }

    private static func parse(
        _ data: Data
    ) -> Result<BridgeReadiness, OwnedBridgeLaunchError> {
        guard let record = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              record["event"] as? String == "listening",
              let rawTransport = record["transport"] as? String,
              let transport = NativeTransportKind(rawValue: rawTransport),
              let endpointPath = record[
                transport == .uds ? "socket_path" : "discovery_path"
              ] as? String,
              !endpointPath.isEmpty,
              let rawPID = record["pid"] as? Int,
              rawPID > 0, rawPID <= Int(Int32.max) else {
            return .failure(.malformedReadiness)
        }
        return .success(BridgeReadiness(
            endpointPath: endpointPath, transport: transport, pid: Int32(rawPID)
        ))
    }
}
