import Foundation
import Testing

@testable import BirkinNativeProtocol

private struct NativeInvalidVectorFixture: Decodable {
    let schemaVersion: Int
    let vectors: [NativeInvalidVector]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case vectors
    }
}

private struct NativeInvalidVector: Decodable {
    let name: String
    let frameBase64: String
    let expectedErrorCode: String

    enum CodingKeys: String, CodingKey {
        case name
        case frameBase64 = "frame_base64"
        case expectedErrorCode = "expected_error_code"
    }
}

@Suite("Negative golden vector parity with the Python codec")
struct NativeNegativeGoldenVectorParityTests {
    @Test("Swift refuses every Python invalid vector with the expected stable code")
    func refusesEveryInvalidVector() throws {
        // Given
        guard let url = Bundle.module.url(
            forResource: "native-protocol-invalid-vectors",
            withExtension: "json",
            subdirectory: "GoldenVectors"
        ) else {
            throw GoldenVectorError(description: "negative golden vector fixture is missing")
        }
        let fixture = try JSONDecoder().decode(
            NativeInvalidVectorFixture.self,
            from: Data(contentsOf: url)
        )
        #expect(fixture.schemaVersion == 1)
        #expect(fixture.vectors.count == 20)

        // When / Then
        for vector in fixture.vectors {
            guard let frame = Data(base64Encoded: vector.frameBase64) else {
                throw GoldenVectorError(description: "negative golden vector frame is malformed")
            }
            let error = #expect(throws: NativeProtocolError.self) {
                _ = try NativeFrameCodec.decode(frame: frame)
            }
            #expect(error?.code.rawValue == vector.expectedErrorCode, "vector \(vector.name)")
        }
    }
}
