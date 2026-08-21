import Foundation
import Testing

@testable import BirkinNativeApp
import BirkinNativeProtocol
import BirkinNativeShell

@Suite("Shell mutation controls emit real commands")
struct ShellMutationCommandTests {
    @MainActor
    @Test("every advertised shell control produces a payload-bearing command")
    func everyControlProducesAValidCommand() throws {
        let session = NativeReadySession(
            instanceID: "instance-1",
            serverVersion: "1.0.0",
            currentSessionID: "session-1",
            sessionCapability: "capability-token",
            supportedCommands: ["session.create"]
        )
        let runtime = BirkinApplicationRuntime(socketPath: nil, emit: { _ in })

        for control in ShellMutationControl.allCases {
            let request = runtime.command(for: control, session: session)
            #expect(!request.commandType.isEmpty)
            #expect(!request.payload.isEmpty, "\(control) sends an empty payload")
            for pair in request.payload.pairs {
                guard case .string(let text) = pair.value else { continue }
                #expect(!text.isEmpty, "\(control) sends an empty \(pair.key)")
            }
        }
    }

    @MainActor
    @Test("the new session control carries a distinct canonical session id")
    func newSessionCarriesADistinctIdentifier() throws {
        let session = NativeReadySession(
            instanceID: "instance-1",
            serverVersion: "1.0.0",
            currentSessionID: "session-1",
            sessionCapability: "capability-token",
            supportedCommands: ["session.create"]
        )
        let runtime = BirkinApplicationRuntime(socketPath: nil, emit: { _ in })

        let first = runtime.command(for: .newSession, session: session)
        let second = runtime.command(for: .newSession, session: session)

        #expect(first.commandType == "session.create")
        #expect(first.payload["session_id"] != second.payload["session_id"])
        #expect(first.commandID != second.commandID)
    }
}
