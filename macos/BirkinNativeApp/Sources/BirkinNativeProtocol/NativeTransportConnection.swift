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
            let transcript = try negotiate(
                socket: socket,
                hello: hello,
                authentication: .uds
            )
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
        let udsSocket: NativeSocket
        do {
            udsSocket = try NativeSocket.connectUDS(path: udsSocketPath)
        } catch let error as NativeTransportError where error.allowsLoopbackFallback {
            apply(.udsUnavailable(reason: error.description))
            return try connectLoopback(discoveryPath: discoveryPath, hello: hello)
        } catch {
            apply(.failed(reason: String(describing: error)))
            throw error
        }
        defer { udsSocket.close() }
        apply(.socketConnected(.uds))
        do {
            let transcript = try negotiate(
                socket: udsSocket,
                hello: hello,
                authentication: .uds
            )
            acceptNegotiated(transcript.session)
            return transcript
        } catch {
            // Once a UDS peer exists, every authentication, identity, version,
            // protocol, malformed-frame, and permission failure is terminal.
            apply(.failed(reason: String(describing: error)))
            throw error
        }
    }

    private func connectLoopback(
        discoveryPath: String,
        hello: NativeHello
    ) throws -> NativeHandshakeTranscript {
        do {
            let record = try JSONDecoder().decode(
                NativeDiscoveryRecord.self,
                from: Data(contentsOf: URL(fileURLWithPath: discoveryPath))
            )
            guard record.transport == NativeTransportKind.loopback.rawValue,
                  record.host == "127.0.0.1",
                  record.protocolVersions.contains(NativeProtocol.version)
            else {
                throw NativeTransportError(
                    "loopback discovery record is unsupported", code: .malformed
                )
            }
            let socket = try NativeSocket.connectLoopback(host: record.host, port: record.port)
            defer { socket.close() }
            apply(.socketConnected(.loopback))
            let transcript = try negotiate(
                socket: socket,
                hello: hello,
                authentication: .loopback(secret: record.bootstrapSecret)
            )
            guard transcript.session.instanceID == record.instanceID,
                  transcript.session.serverVersion == record.serverVersion else {
                throw NativeTransportError(
                    "ready identity does not match discovery", code: .identity
                )
            }
            acceptNegotiated(transcript.session)
            return transcript
        } catch {
            apply(.failed(reason: String(describing: error)))
            throw error
        }
    }
}
