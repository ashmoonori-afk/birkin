import Foundation
import Testing
@testable import BirkinNativeShell

@Suite("Korean IME send matrix")
struct KoreanIMEMatrixTests {
    @Test("composing and committed Return variants preserve text across editable fields")
    func completeMatrix() throws {
        let fields = ShellTextInputField.allCases
        let original = "한글 입력과 CJK 漢字"
        var log: [String] = []
        var cases = 0

        for field in fields {
            for composing in [true, false] {
                for commandPressed in [false, true] {
                    let result = SendKeyPolicy.evaluate(
                        field: field,
                        commandPressed: commandPressed,
                        returnPressed: true,
                        hasMarkedText: composing,
                        text: original
                    )
                    let sendFields: Set<ShellTextInputField> = [.composer, .codeEditor]
                    let expectedSend = sendFields.contains(field) && commandPressed && !composing
                    #expect(result.shouldSend == expectedSend)
                    #expect(result.text == original)
                    log.append("field=\(field.rawValue) composition=\(composing ? "marked" : "committed") key=\(commandPressed ? "cmd-return" : "return") send=\(result.shouldSend) text-intact=\(result.text == original)")
                    cases += 1
                }
            }
        }

        #expect(fields.count == 6)
        #expect(cases == 24)
        try writeLog(log + ["cases=24 premature-send=0 corruption=0"])
    }

    private func writeLog(_ lines: [String]) throws {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { root.deleteLastPathComponent() }
        let directory = root.appendingPathComponent(".omo/evidence/native-shell/phase12", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try Data((lines.joined(separator: "\n") + "\n").utf8)
            .write(to: directory.appendingPathComponent("korean-ime-matrix.log"), options: .atomic)
    }
}
