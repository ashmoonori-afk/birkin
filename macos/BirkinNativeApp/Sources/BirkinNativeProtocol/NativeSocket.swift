import Darwin
import Foundation

final class NativeSocket: @unchecked Sendable {
    private var descriptor: Int32
    private let sendLock = NSLock()

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

    static func connectLoopback(host: String, port: UInt16) throws -> NativeSocket {
        guard host == "127.0.0.1" else {
            throw NativeTransportError("loopback host must be 127.0.0.1")
        }
        let descriptor = Darwin.socket(AF_INET, SOCK_STREAM, 0)
        guard descriptor >= 0 else { throw systemError("socket") }
        let socket = NativeSocket(descriptor: descriptor)
        do {
            try socket.configureTimeouts()
            var address = sockaddr_in()
            address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
            address.sin_family = sa_family_t(AF_INET)
            address.sin_port = port.bigEndian
            guard inet_pton(AF_INET, host, &address.sin_addr) == 1 else {
                throw NativeTransportError("loopback address is invalid")
            }
            let result = withUnsafePointer(to: &address) { pointer in
                pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    Darwin.connect(
                        descriptor,
                        $0,
                        socklen_t(MemoryLayout<sockaddr_in>.size)
                    )
                }
            }
            guard result == 0 else { throw systemError("connect loopback socket") }
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
        sendLock.lock()
        defer { sendLock.unlock() }
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
