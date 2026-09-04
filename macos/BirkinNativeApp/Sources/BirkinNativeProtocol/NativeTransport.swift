import Foundation

public struct NativeHello: Equatable, Sendable {
    public let client: String
    public let clientVersion: String
    public let clientBuild: String
    public let surface: String
    public let viewID: String

    public init(
        client: String,
        clientVersion: String,
        clientBuild: String,
        surface: String,
        viewID: String
    ) {
        self.client = client
        self.clientVersion = clientVersion
        self.clientBuild = clientBuild
        self.surface = surface
        self.viewID = viewID
    }

    func envelope(bootstrapSecret: String?) -> NativeEnvelope {
        NativeEnvelope(
            kind: .hello,
            id: "hello-\(UUID().uuidString)",
            body: [
                "client": .string(client),
                "client_version": .string(clientVersion),
                "client_build": .string(clientBuild),
                "supported_protocol_versions": .array([.int(NativeProtocol.version)]),
                "surface": .string(surface),
                "view_id": .string(viewID),
                "bootstrap_secret": bootstrapSecret.map(NativeJSONValue.string) ?? .null,
            ]
        )
    }
}

public struct NativeHandshakeTranscript: Equatable, Sendable {
    public let hello: NativeEnvelope
    public let ready: NativeEnvelope
    public let transport: NativeTransportKind
    public let session: NativeReadySession
}

public struct NativeTransportError: Error, Equatable, CustomStringConvertible, Sendable {
    public enum Code: String, Equatable, Sendable {
        case endpointUnavailable
        case permissionDenied
        case authentication
        case identity
        case version
        case protocolViolation
        case malformed
        case other
    }

    public let code: Code
    public let reason: String
    public var description: String { reason }
    public var allowsLoopbackFallback: Bool { code == .endpointUnavailable }

    public init(_ reason: String, code: Code = .other) {
        self.code = code
        self.reason = reason
    }
}

struct NativeDiscoveryRecord: Decodable {
    let transport: String
    let host: String
    let port: UInt16
    let instanceID: String
    let serverVersion: String
    let protocolVersions: [Int]
    let bootstrapSecret: String

    enum CodingKeys: String, CodingKey {
        case transport, host, port
        case instanceID = "instance_id"
        case serverVersion = "server_version"
        case protocolVersions = "protocol_versions"
        case bootstrapSecret = "bootstrap_secret"
    }
}
