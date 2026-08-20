import Foundation

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
            acceptNegotiated(transcript.session)
            return transcript
        } catch {
            apply(.failed(reason: String(describing: error)))
            throw error
        }
    }

    public func connectWithFallback(
        udsSocketPath: String,
        discoveryPath: String,
        hello: NativeHello
    ) throws -> NativeHandshakeTranscript {
        apply(.connect)
        do {
            let socket = try NativeSocket.connectUDS(path: udsSocketPath)
            defer { socket.close() }
            apply(.socketConnected(.uds))
            let transcript = try negotiate(socket: socket, hello: hello, secret: nil, as: .uds)
            acceptNegotiated(transcript.session)
            return transcript
        } catch {
            apply(.udsUnavailable(reason: String(describing: error)))
        }

        do {
            let record = try JSONDecoder().decode(
                NativeDiscoveryRecord.self,
                from: Data(contentsOf: URL(fileURLWithPath: discoveryPath))
            )
            guard record.transport == NativeTransportKind.loopback.rawValue,
                  record.host == "127.0.0.1",
                  record.protocolVersions.contains(NativeProtocol.version)
            else {
                throw NativeTransportError("loopback discovery record is unsupported")
            }
            let socket = try NativeSocket.connectLoopback(host: record.host, port: record.port)
            defer { socket.close() }
            apply(.socketConnected(.loopback))
            let transcript = try negotiate(
                socket: socket,
                hello: hello,
                secret: record.bootstrapSecret,
                as: .loopback
            )
            guard transcript.session.instanceID == record.instanceID,
                  transcript.session.serverVersion == record.serverVersion
            else {
                throw NativeTransportError("ready identity does not match discovery")
            }
            acceptNegotiated(transcript.session)
            return transcript
        } catch {
            apply(.failed(reason: String(describing: error)))
            throw error
        }
    }
}
