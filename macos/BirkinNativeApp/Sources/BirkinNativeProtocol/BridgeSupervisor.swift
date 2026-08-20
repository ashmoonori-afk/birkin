import Foundation

public protocol SupervisedBridgeProcess: AnyObject {
    var pid: Int32 { get }
    func terminate()
}

public enum BridgeSupervisorState: Equatable, Sendable {
    case idle
    case attachedExternal(pid: Int32)
    case runningOwned(pid: Int32)
    case stopped(reason: String)
}

public struct BridgeSupervisorDiagnostic: Equatable, Sendable {
    public let timestamp: Date
    public let code: String
    public let message: String
}

/// Owns only child processes returned by this instance's spawn closure.
/// Discovery of any existing endpoint is navigation/replay state, never ownership.
public final class OwnedBridgeSupervisor {
    public private(set) var state: BridgeSupervisorState = .idle
    public private(set) var diagnostics: [BridgeSupervisorDiagnostic] = []

    private let clock: () -> Date
    private let spawn: () throws -> any SupervisedBridgeProcess
    private var owned: (any SupervisedBridgeProcess)?
    private var crashTimes: [Date] = []
    private let diagnosticCapacity: Int

    public init(
        diagnosticCapacity: Int = 20,
        clock: @escaping () -> Date = Date.init,
        spawn: @escaping () throws -> any SupervisedBridgeProcess
    ) {
        precondition(diagnosticCapacity > 0)
        self.diagnosticCapacity = diagnosticCapacity
        self.clock = clock
        self.spawn = spawn
    }

    public func attachExisting(pid: Int32) {
        guard owned == nil, pid > 0 else { return }
        state = .attachedExternal(pid: pid)
        record("external_bridge_attached", "Attached to user-managed bridge.")
    }

    @discardableResult
    public func startOwnedIfNeeded() -> Bool {
        switch state {
        case .attachedExternal, .runningOwned, .stopped: return false
        case .idle: return launchOwned()
        }
    }

    public func observeExit(pid: Int32, status: Int32) {
        guard let child = owned, child.pid == pid else {
            record("external_bridge_untouched", "Ignored exit from an unowned bridge.")
            return
        }
        owned = nil
        let time = clock()
        crashTimes = crashTimes.filter {
            let age = time.timeIntervalSince($0)
            return age >= 0 && age < 60
        }
        crashTimes.append(time)
        record("owned_bridge_exited", "Owned bridge exited with status \(status).")
        if crashTimes.count >= 5 {
            state = .stopped(reason: "crash_loop")
            record(
                "restart_ceiling_reached",
                "Bridge stopped after five crashes within sixty seconds."
            )
            return
        }
        _ = launchOwned()
    }

    public func shutdown() {
        switch state {
        case .attachedExternal:
            record("external_bridge_untouched", "User-managed bridge left running.")
        case .runningOwned:
            owned?.terminate()
            record("owned_bridge_terminated", "Terminated app-owned bridge.")
        case .idle, .stopped: break
        }
        owned = nil
        state = .stopped(reason: "app_shutdown")
    }

    @discardableResult
    private func launchOwned() -> Bool {
        do {
            let child = try spawn()
            guard child.pid > 0 else {
                state = .stopped(reason: "launch_failed")
                record("launch_failed", "Bridge launch returned an invalid process.")
                return false
            }
            owned = child
            state = .runningOwned(pid: child.pid)
            record("owned_bridge_started", "Started app-owned bridge.")
            return true
        } catch {
            state = .stopped(reason: "launch_failed")
            record("launch_failed", "Bridge launch failed.")
            return false
        }
    }

    private func record(_ code: String, _ message: String) {
        diagnostics.append(BridgeSupervisorDiagnostic(
            timestamp: clock(), code: code,
            message: String(message.prefix(160))
        ))
        if diagnostics.count > diagnosticCapacity {
            diagnostics.removeFirst(diagnostics.count - diagnosticCapacity)
        }
    }
}

public final class FoundationBridgeProcess: SupervisedBridgeProcess {
    private let process: Process

    public var pid: Int32 { process.processIdentifier }

    public init(process: Process) { self.process = process }

    public func terminate() {
        if process.isRunning { process.terminate() }
    }
}
