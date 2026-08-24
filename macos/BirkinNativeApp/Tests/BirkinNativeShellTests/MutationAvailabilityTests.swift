import Foundation
import Testing

@testable import BirkinNativeProtocol
@testable import BirkinNativeShell

@Suite("Native shell mutation availability")
struct MutationAvailabilityTests {
    private let now = Date(timeIntervalSince1970: 1_787_238_000)

    @Test("mutations require ready transport and a live capability")
    func readyAndLiveCapabilityAreBothRequired() {
        let live = session(expiresIn: 60)
        let expired = session(expiresIn: -1)
        let states: [(NativeConnectionState, Bool, String?)] = [
            (.ready(live), true, nil),
            (.fallback(.ready(live)), true, nil),
            (.ready(expired), false, "Connection capability expired."),
            (.disconnected, false, "Disconnected from the Python authority."),
            (.connecting, false, "Connection is not ready."),
            (.replaying(live), false, "Canonical state is replaying."),
            (.failed(reason: "bridge stopped"), false, "bridge stopped"),
        ]

        for (state, expectedEnabled, expectedReason) in states {
            let availability = MutationAvailability(state: state, now: now)
            #expect(availability.isEnabled == expectedEnabled)
            #expect(availability.disabledReason == expectedReason)
        }
    }

    private func session(expiresIn interval: TimeInterval) -> NativeReadySession {
        NativeReadySession(
            instanceID: "instance-1",
            serverVersion: "1.0",
            sessionCapability: "token",
            capabilityExpiresAt: now.addingTimeInterval(interval),
            capabilityHardExpiresAt: now.addingTimeInterval(120)
        )
    }
}
