import AppKit
import BirkinNativeProtocol
import SwiftUI
import Testing
@testable import BirkinNativeShell

@Suite("Contrast large text and reduced motion")
struct VisualAccessibilityTests {
    @Test("every connection state has a non-color text and symbol indicator")
    func statusIsNeverColorOnly() {
        let now = Date(timeIntervalSince1970: 1_000)
        let session = NativeReadySession(
            instanceID: "instance", serverVersion: "1", sessionCapability: "token",
            capabilityExpiresAt: now.addingTimeInterval(60),
            capabilityHardExpiresAt: now.addingTimeInterval(120)
        )
        let states: [NativeConnectionState] = [
            .disconnected, .connecting, .negotiating(.uds), .ready(session),
            .replaying(session),
            .fallback(.connecting(reason: "socket unavailable")),
            .fallback(.negotiating), .fallback(.ready(session)),
            .failed(reason: "version mismatch"), .failed(reason: "bridge unavailable"),
        ]
        let indicators = states.map { VisualAccessibilityContract.statusIndicator(for: $0) }
        #expect(indicators.count == 10)
        #expect(indicators.allSatisfy { !$0.text.isEmpty && !$0.symbolName.isEmpty })
        #expect(Set(indicators.map { "\($0.text)|\($0.symbolName)" }).count >= 6)
    }

    @MainActor
    @Test("accessibility profiles render without fixed-window clipping")
    func renderProfiles() throws {
        let plan = ShellLayoutPlan(windowWidth: 960, dynamicTypeSize: .accessibility5)
        #expect(plan.mode == .panelNavigation)
        #expect(plan.statusAllowsVerticalReflow)
        #expect(plan.columnsScrollIndependently)

        let base = NativeShellView(
            store: NativeProjectionStore(),
            connectionState: .failed(reason: "Python bridge stopped; diagnostics remain available.")
        )
        try snapshot(
            base.environment(\.dynamicTypeSize, .accessibility5),
            named: "large-text-max.png"
        )
        try snapshot(
            base.environment(
                \.shellVisualSettings,
                ShellVisualSettings(increasedContrast: true)
            ),
            named: "increased-contrast.png"
        )
        try snapshot(
            base.environment(
                \.shellVisualSettings,
                ShellVisualSettings(reduceMotion: true)
            ),
            named: "reduced-motion.png"
        )
        #expect(!VisualAccessibilityContract.animationsEnabled(reduceMotion: true))
    }

    @MainActor
    private func snapshot<V: View>(_ view: V, named: String) throws {
        let rendered = view.frame(width: 960, height: 760)
        let renderer = ImageRenderer(content: rendered)
        renderer.scale = 1
        let image = try #require(renderer.nsImage)
        #expect(image.size == NSSize(width: 960, height: 760))
        let tiff = try #require(image.tiffRepresentation)
        let bitmap = try #require(NSBitmapImageRep(data: tiff))
        let png = try #require(bitmap.representation(using: .png, properties: [:]))
        #expect(png.count > 10_000)
        try png.write(to: evidenceURL(named), options: .atomic)
    }

    private func evidenceURL(_ name: String) throws -> URL {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { root.deleteLastPathComponent() }
        let directory = root.appendingPathComponent(".omo/evidence/native-shell/phase12", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory.appendingPathComponent(name)
    }
}
