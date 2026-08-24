import Foundation
import Testing

@testable import BirkinNativeProtocol

private let harnessSignalTimeout = DispatchTimeInterval.seconds(60)

final class LockedLine: @unchecked Sendable {
    private let lock = NSLock()
    private var value = Data()

    func append(_ byte: Data) {
        lock.lock()
        value.append(byte)
        lock.unlock()
    }

    func text() -> String? {
        lock.lock()
        defer { lock.unlock() }
        return String(data: value, encoding: .utf8)
    }
}

struct HarnessLaunchOptions {
    let terminal: Bool
    let serverVersion: String?
    let root: URL?

    init(
        terminal: Bool = false,
        serverVersion: String? = nil,
        root: URL? = nil
    ) {
        self.terminal = terminal
        self.serverVersion = serverVersion
        self.root = root
    }
}

struct HarnessReadiness {
    let process: Process
    let stdout: Pipe
    let root: URL
    let record: [String: Any]
    let exit: DispatchSemaphore

    static func launch(
        transport: String,
        options: HarnessLaunchOptions = HarnessLaunchOptions()
    ) throws -> HarnessReadiness {
        let package = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let repository = package.deletingLastPathComponent().deletingLastPathComponent()
        let root = options.root
            ?? URL(fileURLWithPath: "/private/tmp/birkin-swift-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)

        let process = Process()
        let stdout = Pipe()
        let exit = DispatchSemaphore(value: 0)
        process.executableURL = repository.appendingPathComponent(".venv/bin/python3")
        process.arguments = [
            "scripts/native/swift_transport_harness.py",
            "--transport", transport, "--root", root.path,
            "--connections", "1",
        ] + (options.terminal ? ["--terminal"] : [])
        process.currentDirectoryURL = repository
        process.environment = ProcessInfo.processInfo.environment.merging(
            options.serverVersion.map {
                ["BIRKIN_TEST_NATIVE_SERVER_VERSION": $0]
            } ?? [:],
            uniquingKeysWith: { _, override in override }
        )
        process.standardOutput = stdout
        process.standardError = FileHandle.standardError
        process.terminationHandler = { _ in exit.signal() }

        let line = LockedLine()
        let ready = DispatchSemaphore(value: 0)
        DispatchQueue.global().async {
            while true {
                let byte = stdout.fileHandleForReading.readData(ofLength: 1)
                if byte.isEmpty || byte == Data([0x0a]) { break }
                line.append(byte)
            }
            ready.signal()
        }
        try process.run()
        guard ready.wait(timeout: .now() + harnessSignalTimeout) == .success,
              let text = line.text(),
              let data = text.data(using: .utf8),
              let record = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              record["event"] as? String == "listening"
        else {
            process.terminate()
            throw HarnessError.readinessTimeout
        }
        return HarnessReadiness(
            process: process, stdout: stdout, root: root, record: record, exit: exit
        )
    }

    func finish(removeRoot: Bool = true) throws -> String {
        guard exit.wait(timeout: .now() + harnessSignalTimeout) == .success else {
            process.terminate()
            throw HarnessError.exitTimeout
        }
        let tail = stdout.fileHandleForReading.readDataToEndOfFile()
        let receipt = String(decoding: tail, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        if removeRoot {
            try FileManager.default.removeItem(at: root)
        }
        return receipt
    }
}

enum HarnessError: Error {
    case readinessTimeout
    case exitTimeout
    case malformedReadiness
}

let integrationHello = NativeHello(
    client: "birkin-macos",
    clientVersion: "1.0.0",
    clientBuild: "100",
    surface: "macos",
    viewID: "main"
)
