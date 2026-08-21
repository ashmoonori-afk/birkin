import Foundation
import Testing

@testable import BirkinNativeApp
import BirkinNativeProtocol

@Suite("Packaged application Browser lifecycle", .serialized)
struct BirkinApplicationBrowserIntegrationTests {
    @MainActor
    @Test("Browser start and local navigation each advance canonical revision")
    func startsAndNavigatesLocalPage() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/bk-browser-\(UUID().uuidString)")
        let page = try LocalBrowserPage()
        let port = try #require(page.url.port)
        let rulesData = try JSONSerialization.data(withJSONObject: [[
            "host": "127.0.0.1", "cidr": "127.0.0.1/32", "port": port,
        ]])
        let rules = try #require(String(data: rulesData, encoding: .utf8))
        let harness = try AppHarness.launch(root: root, environment: [
            "BIRKIN_HOME": root.appendingPathComponent("home").path,
            "BIRKIN_BROWSER_PRIVATE_NETWORK_RULES": rules,
        ])
        let socketPath = try #require(harness.socketPath)
        let runtimeEvents = RuntimeEventRecorder()
        let journeyEvents = JourneyEventLog()
        let runtime = BirkinApplicationRuntime(socketPath: socketPath, emit: {
            runtimeEvents.record($0)
            journeyEvents.record($0)
        })
        defer {
            runtime.stop()
            harness.terminate()
            page.close()
            try? FileManager.default.removeItem(at: root)
        }

        try await withTimeout("runtime start", seconds: 60) { await runtime.start() }
        try await withTimeout("initial Browser surface") {
            try await runtimeEvents.wait(for: "surface-applied name=browser_aside")
        }
        let initialRevision = try #require(
            runtime.store.surface(named: "browser_aside")?.revision
        )
        let runner = PackagedJourneyRunner(
            configuration: PackagedJourneyConfiguration(
                evidenceRoot: root.appendingPathComponent("evidence"),
                workspaceRoot: root,
                browserURL: page.url
            ),
            runtime: runtime,
            events: journeyEvents
        )

        try await runner.driveBrowser()

        let surface = try #require(runtime.store.surface(named: "browser_aside"))
        let presentation = try #require(BrowserAsidePresentation(store: runtime.store))
        #expect(surface.revision == initialRevision + 2)
        #expect(presentation.isLive)
        #expect(presentation.displayURL == page.origin.absoluteString)
        #expect(presentation.frameRevision > 0)
        #expect(runner.steps.last?.name == "browser-navigate-live")

        // Closing the live subscription lets Python close Chromium and its
        // private profile before the harness process is reaped.
        runtime.stop()
        try await withTimeout("Browser bridge cleanup", seconds: 60) {
            await Task.detached { harness.process.waitUntilExit() }.value
        }
        #expect(!harness.process.isRunning)
    }
}

private final class LocalBrowserPage: @unchecked Sendable {
    let process: Process
    let url: URL

    var origin: URL {
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)!
        components.path = "/"
        components.query = nil
        components.fragment = nil
        return components.url!
    }

    init() throws {
        process = Process()
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = ["-u", "-c", """
import http.server
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'<!doctype html><h1>BIRKIN PACKAGED JOURNEY</h1>'
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args): pass
server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
print(server.server_port, flush=True)
server.serve_forever()
"""]
        process.standardOutput = output
        process.standardError = FileHandle.standardError
        try process.run()
        do {
            let line = try Self.readLine(from: output.fileHandleForReading)
            guard let port = Int(line),
                  let address = URL(string: "http://127.0.0.1:\(port)/packaged-journey") else {
                throw AppRuntimeTestError.malformedReadiness
            }
            url = address
        } catch {
            process.terminate()
            process.waitUntilExit()
            throw error
        }
    }

    func close() {
        guard process.isRunning else { return }
        process.terminate()
        process.waitUntilExit()
    }

    private static func readLine(from handle: FileHandle) throws -> String {
        let bytes = LockedBytes()
        let ready = DispatchSemaphore(value: 0)
        DispatchQueue.global().async {
            while true {
                let byte = handle.readData(ofLength: 1)
                if byte.isEmpty || byte == Data([0x0a]) { break }
                bytes.append(byte)
            }
            ready.signal()
        }
        guard ready.wait(timeout: .now() + 20) == .success else {
            throw AppRuntimeTestError.timeout("local Browser page readiness")
        }
        return bytes.text()
    }
}
