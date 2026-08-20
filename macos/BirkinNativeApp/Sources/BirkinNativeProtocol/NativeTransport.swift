import Darwin
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
    public let reason: String
    public var description: String { reason }

    init(_ reason: String) {
        self.reason = reason
    }
}

extension NativeTransportActor {
    public func connectUDS(
        socketPath: String,
        hello: NativeHello
    ) throws -> NativeHandshakeTranscript {
        apply(.connect)
        do {
            let socket = try NativeSocket.connectUDS(path: socketPath)
            defer { socket.close() }
            apply(.socketConnected(.uds))
            let transcript = try negotiate(socket: socket, hello: hello, secret: nil, as: .uds)
            apply(.negotiated(transcript.session))
            return transcript
        } catch {
            apply(.failed(reason: String(describing: error)))
            throw error
        }
    }

    private func negotiate(
        socket: NativeSocket,
        hello: NativeHello,
        secret: String?,
        as transport: NativeTransportKind
    ) throws -> NativeHandshakeTranscript {
        let outbound = hello.envelope(bootstrapSecret: secret)
        try socket.send(NativeFrameCodec.encode(outbound))
        let inbound = try NativeFrameCodec.decode(frame: socket.receiveFrame())
        guard inbound.kind == .ready, inbound.inReplyTo == outbound.id else {
            throw NativeTransportError("server did not return correlated ready")
        }
        guard case .string(let wireTransport) = inbound.body["transport"],
              wireTransport == transport.rawValue,
              case .string(let instanceID) = inbound.body["instance_id"],
              case .string(let serverVersion) = inbound.body["server_version"],
              case .object(let capability) = inbound.body["capability"],
              case .string(let token) = capability["token"]
        else {
            throw NativeTransportError("ready body is missing transport session fields")
        }
        return NativeHandshakeTranscript(
            hello: outbound,
            ready: inbound,
            transport: transport,
            session: NativeReadySession(
                instanceID: instanceID,
                serverVersion: serverVersion,
                sessionCapability: token
            )
        )
    }
}

private final class NativeSocket {
    private var descriptor: Int32

    private init(descriptor: Int32) {
        self.descriptor = descriptor
    }

    static func connectUDS(path: String) throws -> NativeSocket {
        let pathBytes = Array(path.utf8) + [0]
        guard pathBytes.count <= MemoryLayout.size(ofValue: sockaddr_un().sun_path) else {
            throw NativeTransportError("Unix socket path exceeds the platform limit")
        }
        let descriptor = Darwin.socket(AF_UNIX, SOCK_STREAM, 0)
        guard descriptor >= 0 else { throw systemError("socket") }
        let socket = NativeSocket(descriptor: descriptor)
        do {
            try socket.configureTimeouts()
            var address = sockaddr_un()
            address.sun_family = sa_family_t(AF_UNIX)
            withUnsafeMutableBytes(of: &address.sun_path) { destination in
                destination.copyBytes(from: pathBytes)
            }
            let result = withUnsafePointer(to: &address) { pointer in
                pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    Darwin.connect(
                        descriptor,
                        $0,
                        socklen_t(MemoryLayout<sockaddr_un>.size)
                    )
                }
            }
            guard result == 0 else { throw systemError("connect Unix socket") }
            return socket
        } catch {
            socket.close()
            throw error
        }
    }

    func close() {
        guard descriptor >= 0 else { return }
        _ = Darwin.close(descriptor)
        descriptor = -1
    }

    func send(_ data: Data) throws {
        try data.withUnsafeBytes { raw in
            var sent = 0
            while sent < raw.count {
                let count = Darwin.send(
                    descriptor,
                    raw.baseAddress!.advanced(by: sent),
                    raw.count - sent,
                    0
                )
                guard count > 0 else { throw Self.systemError("send") }
                sent += count
            }
        }
    }

    func receiveFrame() throws -> Data {
        let header = try receive(count: 4)
        let declared = header.reduce(0) { $0 << 8 | Int($1) }
        guard declared <= NativeProtocol.maxFrameBytes else {
            throw NativeTransportError("native frame exceeds limit")
        }
        var frame = header
        frame.append(try receive(count: declared))
        return frame
    }

    private func receive(count: Int) throws -> Data {
        var result = Data(count: count)
        var received = 0
        try result.withUnsafeMutableBytes { raw in
            while received < count {
                let amount = Darwin.recv(
                    descriptor,
                    raw.baseAddress!.advanced(by: received),
                    count - received,
                    0
                )
                guard amount > 0 else {
                    if amount == 0 { throw NativeTransportError("connection closed during frame") }
                    throw Self.systemError("receive")
                }
                received += amount
            }
        }
        return result
    }

    private func configureTimeouts() throws {
        var timeout = timeval(tv_sec: 10, tv_usec: 0)
        let size = socklen_t(MemoryLayout<timeval>.size)
        guard setsockopt(descriptor, SOL_SOCKET, SO_RCVTIMEO, &timeout, size) == 0,
              setsockopt(descriptor, SOL_SOCKET, SO_SNDTIMEO, &timeout, size) == 0
        else {
            throw Self.systemError("configure socket timeout")
        }
        var enabled: Int32 = 1
        guard setsockopt(
            descriptor,
            SOL_SOCKET,
            SO_NOSIGPIPE,
            &enabled,
            socklen_t(MemoryLayout<Int32>.size)
        ) == 0 else {
            throw Self.systemError("configure socket")
        }
    }

    private static func systemError(_ operation: String) -> NativeTransportError {
        NativeTransportError("\(operation) failed: \(String(cString: strerror(errno)))")
    }
}
