import AppKit
import CoreGraphics
import CryptoKit
import Foundation
import Testing

@testable import BirkinNativeApp

@Suite("Compositor-backed packaged window capture")
@MainActor
struct PackagedWindowCaptureTests {
    @Test("capture rejects missing Screen Recording permission")
    func rejectsMissingPermission() throws {
        let window = makeWindow()
        let capture = PackagedWindowCapture(
            preflight: { false },
            windows: { [window] },
            metadata: { _ in .valid },
            image: { _ in Self.testImage() }
        )

        #expect(throws: PackagedWindowCaptureError.permissionRequired) {
            try capture.capture(
                to: temporaryURL(),
                focusTarget: "section:conversation",
                focusGeneration: 1
            )
        }
    }

    @Test("window readiness waits for an application update event")
    func waitsForOwnedWindowEvent() async throws {
        var windows: [NSWindow] = []
        let capture = PackagedWindowCapture(
            preflight: { true },
            windows: { windows },
            metadata: { _ in .valid },
            image: { _ in Self.testImage() }
        )
        let (registrations, registration) = AsyncStream<Void>.makeStream()
        var iterator = registrations.makeAsyncIterator()
        let waiter = Task { @MainActor in
            try await capture.waitForOwnedWindow(
                onWaiting: { registration.yield() }
            )
        }
        _ = await iterator.next()

        windows = [makeWindow()]
        NotificationCenter.default.post(
            name: NSApplication.didUpdateNotification,
            object: NSApplication.shared
        )

        try await waiter.value
    }

    @Test("capture requires exactly one owned Birkin window")
    func requiresUniqueOwnedWindow() throws {
        let first = makeWindow()
        let second = makeWindow()
        let capture = PackagedWindowCapture(
            preflight: { true },
            windows: { [first, second] },
            metadata: { _ in .valid },
            image: { _ in Self.testImage() }
        )

        #expect(throws: PackagedWindowCaptureError.windowCount(2)) {
            try capture.capture(
                to: temporaryURL(),
                focusTarget: "section:conversation",
                focusGeneration: 1
            )
        }
    }

    @Test("capture rejects a window whose owner changes during acquisition")
    func rejectsOwnerChangeDuringCapture() throws {
        let window = makeWindow()
        let output = temporaryURL()
        let sequence = WindowMetadataSequence([
            .valid,
            PackagedWindowMetadata(
                ownerPID: getpid() + 1,
                layer: 0,
                bounds: .init(x: 0, y: 0, width: 1_280, height: 800)
            ),
        ])
        let capture = PackagedWindowCapture(
            preflight: { true },
            windows: { [window] },
            metadata: { _ in sequence.next() },
            image: { _ in Self.testImage() }
        )

        #expect(throws: PackagedWindowCaptureError.wrongOwner) {
            try capture.capture(
                to: output,
                focusTarget: "section:conversation",
                focusGeneration: 1
            )
        }
        #expect(!FileManager.default.fileExists(atPath: output.path))
    }

    @Test("capture rejects a flat compositor image")
    func rejectsFlatImage() throws {
        let window = makeWindow()
        let output = temporaryURL()
        let capture = PackagedWindowCapture(
            preflight: { true },
            windows: { [window] },
            metadata: { _ in .valid },
            image: { _ in Self.flatImage() }
        )

        #expect(throws: PackagedWindowCaptureError.contentlessImage) {
            try capture.capture(
                to: output,
                focusTarget: "section:conversation",
                focusGeneration: 1
            )
        }
        #expect(!FileManager.default.fileExists(atPath: output.path))
    }

    @Test("capture writes only the owned compositor window with a receipt")
    func writesOwnedWindow() throws {
        let window = makeWindow()
        let output = temporaryURL()
        let capture = PackagedWindowCapture(
            preflight: { true },
            windows: { [window] },
            metadata: { _ in .valid },
            image: { _ in Self.testImage() },
            recognizer: { _ in ["한국어", "日本語", "漢字"] }
        )

        let receipt = try capture.capture(
            to: output,
            focusTarget: "section:conversation",
            focusGeneration: 7
        )

        #expect(FileManager.default.fileExists(atPath: output.path))
        #expect((try Data(contentsOf: output)).count > 100)
        #expect(receipt.source == "cg-window")
        #expect(receipt.ownerPID == getpid())
        #expect(receipt.windowNumber == window.windowNumber)
        #expect(receipt.focusTarget == "section:conversation")
        #expect(receipt.focusGeneration == 7)
        #expect(receipt.pixelWidth == 32)
        #expect(receipt.pixelHeight == 24)
        #expect(receipt.cjkOCRMarkers == ["한국어", "日本語", "漢字"])
        let expectedDigest = SHA256.hash(data: try Data(contentsOf: output))
            .map { String(format: "%02x", $0) }
            .joined()
        #expect(receipt.pngSHA256 == expectedDigest)
    }

    private func makeWindow() -> NSWindow {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1_280, height: 800),
            styleMask: [.titled, .closable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = BirkinApplicationConfiguration.windowTitle
        return window
    }

    private func temporaryURL() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("birkin-window-\(UUID().uuidString).png")
    }

    private static func testImage() -> CGImage {
        let width = 32
        let height = 24
        let space = CGColorSpaceCreateDeviceRGB()
        let context = CGContext(
            data: nil,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width * 4,
            space: space,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        )!
        for index in 0..<8 {
            context.setFillColor(CGColor(
                red: CGFloat(index) / 7,
                green: CGFloat(7 - index) / 7,
                blue: CGFloat(index % 3) / 2,
                alpha: 1
            ))
            context.fill(CGRect(
                x: index * 4,
                y: 0,
                width: 4,
                height: height
            ))
        }
        return context.makeImage()!
    }

    private static func flatImage() -> CGImage {
        let width = 32
        let height = 24
        let space = CGColorSpaceCreateDeviceRGB()
        let context = CGContext(
            data: nil,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width * 4,
            space: space,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        )!
        context.setFillColor(CGColor(
            red: 0.1,
            green: 0.2,
            blue: 0.3,
            alpha: 1
        ))
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        return context.makeImage()!
    }
}

@MainActor
private final class WindowMetadataSequence {
    private var values: [PackagedWindowMetadata]

    init(_ values: [PackagedWindowMetadata]) {
        self.values = values
    }

    func next() -> PackagedWindowMetadata? {
        values.isEmpty ? nil : values.removeFirst()
    }
}
