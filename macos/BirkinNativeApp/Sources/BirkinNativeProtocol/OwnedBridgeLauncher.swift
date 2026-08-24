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

    public init(
        executable: String,
        leadingArguments: [String] = [],
        serveOptions: [String] = [],
        readinessTimeout: TimeInterval = 30
    ) {
        self.executable = executable
        self.leadingArguments = leadingArguments
        self.serveOptions = serveOptions
        self.readinessTimeout = readinessTimeout
    }

    var argumentList: [String] {
        leadingArguments + ["native-bridge", "serve", "--transport", "uds"] + serveOptions
    }
}

public enum OwnedBridgeLaunchError: Error, Equatable {
    case readinessTimedOut
    case malformedReadiness
}

/// One live bridge process this application started.
public struct LaunchedBridge {
    public let process: FoundationBridgeProcess
    public let socketPath: String
}

/// Starts the shipped bridge command and waits for it to announce its endpoint.
public enum OwnedBridgeLauncher {
    public static func launch(
        _ configuration: OwnedBridgeConfiguration,
        onExit: @escaping @Sendable (Int32, Int32) -> Void
    ) throws -> LaunchedBridge {
        let process = Process()
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: configuration.executable)
        process.arguments = configuration.argumentList
        process.standardOutput = output
        process.standardError = FileHandle.standardError
        try process.run()
        do {
            let readiness = try readEndpoint(
                from: output.fileHandleForReading,
                timeout: configuration.readinessTimeout
            )
            process.terminationHandler = { finished in
                onExit(readiness.pid, finished.terminationStatus)
            }
            return LaunchedBridge(
                process: FoundationBridgeProcess(
                    process: process,
                    supervisedPID: readiness.pid
                ),
                socketPath: readiness.socketPath
            )
        } catch {
            process.terminationHandler = nil
            if process.isRunning { process.terminate() }
            throw error
        }
    }

    private static func readEndpoint(
        from handle: FileHandle,
        timeout: TimeInterval
    ) throws -> BridgeReadiness {
        let bytes = ReadinessBuffer()
        let ready = DispatchSemaphore(value: 0)
        DispatchQueue.global().async {
            while true {
                let byte = handle.readData(ofLength: 1)
                if byte.isEmpty || byte == Data([0x0a]) { break }
                bytes.append(byte)
            }
            ready.signal()
        }
        guard ready.wait(timeout: .now() + timeout) == .success else {
            throw OwnedBridgeLaunchError.readinessTimedOut
        }
        guard let data = bytes.text().data(using: .utf8),
              let record = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              record["event"] as? String == "listening",
              let socketPath = record["socket_path"] as? String,
              !socketPath.isEmpty,
              let rawPID = record["pid"] as? Int,
              rawPID > 0, rawPID <= Int(Int32.max) else {
            throw OwnedBridgeLaunchError.malformedReadiness
        }
        return BridgeReadiness(socketPath: socketPath, pid: Int32(rawPID))
    }
}

private struct BridgeReadiness: Sendable {
    let socketPath: String
    let pid: Int32
}

private final class ReadinessBuffer: @unchecked Sendable {
    private let lock = NSLock()
    private var bytes = Data()

    func append(_ data: Data) { lock.withLock { bytes.append(data) } }
    func text() -> String { lock.withLock { String(decoding: bytes, as: UTF8.self) } }
}
