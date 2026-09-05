import Foundation
import OSLog

/// Native application diagnostics.
///
/// Normal launches write only to the unified log, where the complete event
/// payload is private. The stdout journey protocol exists solely for a fully
/// configured scripted-QA run.
struct NativeDiagnosticsLogger: Sendable {
    static let production = NativeDiagnosticsLogger(isJourneyMode: false)

    private let logger: Logger
    private let journeyOutput: (@Sendable (Data) -> Void)?

    init(
        isJourneyMode: Bool,
        logger: Logger = Logger(
            subsystem: BirkinApplicationConfiguration.bundleIdentifier,
            category: "application"
        ),
        journeyOutput: @escaping @Sendable (Data) -> Void = {
            FileHandle.standardOutput.write($0)
        }
    ) {
        self.logger = logger
        self.journeyOutput = isJourneyMode ? journeyOutput : nil
    }

    func emit(_ message: String) {
        logger.notice(
            "event=\(message, privacy: .private(mask: .hash))"
        )
        journeyOutput?(Self.journeyEventData(message))
    }

    static func journeyEventData(_ message: String) -> Data {
        Data(
            "BIRKIN_APP_EVENT \(JourneyEvidenceRedactor.redact(message))\n".utf8
        )
    }
}
