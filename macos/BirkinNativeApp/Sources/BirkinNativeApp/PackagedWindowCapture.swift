import AppKit
import CoreGraphics
import CryptoKit
import Darwin
import Foundation
import Vision

public struct PackagedWindowMetadata: Equatable, Sendable {
    public let ownerPID: pid_t
    public let layer: Int
    public let bounds: CGRect

    public static var valid: PackagedWindowMetadata {
        PackagedWindowMetadata(
            ownerPID: getpid(),
            layer: 0,
            bounds: CGRect(x: 0, y: 0, width: 1_280, height: 800)
        )
    }
}

public struct PackagedWindowCaptureReceipt: Codable, Equatable, Sendable {
    public let source: String
    public let ownerPID: pid_t
    public let windowNumber: Int
    public let pointWidth: Int
    public let pointHeight: Int
    public let pixelWidth: Int
    public let pixelHeight: Int
    public let focusTarget: String
    public let focusGeneration: UInt64
    public let executablePath: String
    public let pngSHA256: String
    public let cjkOCRMarkers: [String]
}

public enum PackagedWindowCaptureError: Error, Equatable {
    case permissionRequired
    case windowCount(Int)
    case wrongOwner
    case wrongLayer
    case emptyBounds
    case captureFailed
    case contentlessImage
    case pngEncodingFailed
}

@MainActor
public final class PackagedWindowCapture {
    public typealias Metadata =
        @MainActor @Sendable (CGWindowID) -> PackagedWindowMetadata?
    public typealias Image = @MainActor @Sendable (CGWindowID) -> CGImage?
    public typealias Recognizer = @MainActor @Sendable (CGImage) -> [String]
    typealias WindowIDs = @MainActor () -> [CGWindowID]

    public static let cjkSpecimens = ["한국어", "日本語", "漢字"]

    private let preflight: @MainActor @Sendable () -> Bool
    private let windows: @MainActor () -> [NSWindow]
    private let injectedWindowIDs: WindowIDs?
    private let metadata: Metadata
    private let image: Image
    private let recognizer: Recognizer

    public init(
        preflight: @escaping @MainActor @Sendable () -> Bool =
            CGPreflightScreenCaptureAccess,
        windows: @escaping @MainActor () -> [NSWindow] = {
            NSApplication.shared.windows.filter {
                $0.title == BirkinApplicationConfiguration.windowTitle
                    && $0.isVisible
                    && $0.level == .normal
            }
        },
        metadata: @escaping Metadata = PackagedWindowCapture.windowMetadata,
        image: @escaping Image = PackagedWindowCapture.windowImage,
        recognizer: @escaping Recognizer =
            PackagedWindowCapture.recognizedCJKMarkers
    ) {
        self.preflight = preflight
        self.windows = windows
        injectedWindowIDs = nil
        self.metadata = metadata
        self.image = image
        self.recognizer = recognizer
    }

    init(
        preflight: @escaping @MainActor @Sendable () -> Bool,
        windowIDs: @escaping WindowIDs,
        metadata: @escaping Metadata,
        image: @escaping Image,
        recognizer: @escaping Recognizer =
            PackagedWindowCapture.recognizedCJKMarkers
    ) {
        self.preflight = preflight
        windows = { [] }
        injectedWindowIDs = windowIDs
        self.metadata = metadata
        self.image = image
        self.recognizer = recognizer
    }

    public func capture(
        to output: URL,
        focusTarget: String,
        focusGeneration: UInt64
    ) throws -> PackagedWindowCaptureReceipt {
        guard preflight() else {
            throw PackagedWindowCaptureError.permissionRequired
        }
        let windowID: CGWindowID
        let windowNumber: Int
        if let injectedWindowIDs {
            let candidates = injectedWindowIDs()
            guard candidates.count == 1, let candidate = candidates.first else {
                throw PackagedWindowCaptureError.windowCount(candidates.count)
            }
            windowID = candidate
            windowNumber = Int(candidate)
        } else {
            let candidates = windows()
            guard candidates.count == 1, let window = candidates.first else {
                throw PackagedWindowCaptureError.windowCount(candidates.count)
            }
            window.layoutIfNeeded()
            window.displayIfNeeded()
            windowID = CGWindowID(window.windowNumber)
            windowNumber = window.windowNumber
        }
        guard let initialMetadata = metadata(windowID) else {
            throw PackagedWindowCaptureError.captureFailed
        }
        guard initialMetadata.ownerPID == getpid() else {
            throw PackagedWindowCaptureError.wrongOwner
        }
        guard initialMetadata.layer == 0 else {
            throw PackagedWindowCaptureError.wrongLayer
        }
        guard initialMetadata.bounds.width > 0,
              initialMetadata.bounds.height > 0 else {
            throw PackagedWindowCaptureError.emptyBounds
        }
        guard let captured = image(windowID) else {
            throw PackagedWindowCaptureError.captureFailed
        }
        guard let confirmedMetadata = metadata(windowID) else {
            throw PackagedWindowCaptureError.captureFailed
        }
        guard confirmedMetadata.ownerPID == getpid() else {
            throw PackagedWindowCaptureError.wrongOwner
        }
        guard confirmedMetadata.layer == 0 else {
            throw PackagedWindowCaptureError.wrongLayer
        }
        guard confirmedMetadata.bounds.width > 0,
              confirmedMetadata.bounds.height > 0 else {
            throw PackagedWindowCaptureError.emptyBounds
        }
        let representation = NSBitmapImageRep(cgImage: captured)
        guard Self.hasMeaningfulContent(representation) else {
            throw PackagedWindowCaptureError.contentlessImage
        }
        let cjkOCRMarkers = recognizer(captured)
        guard let png = representation.representation(
            using: .png,
            properties: [:]
        ) else {
            throw PackagedWindowCaptureError.pngEncodingFailed
        }
        let pngSHA256 = SHA256.hash(data: png)
            .map { String(format: "%02x", $0) }
            .joined()
        try FileManager.default.createDirectory(
            at: output.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try png.write(to: output, options: .atomic)
        return PackagedWindowCaptureReceipt(
            source: "cg-window",
            ownerPID: getpid(),
            windowNumber: windowNumber,
            pointWidth: Int(confirmedMetadata.bounds.width.rounded()),
            pointHeight: Int(confirmedMetadata.bounds.height.rounded()),
            pixelWidth: captured.width,
            pixelHeight: captured.height,
            focusTarget: focusTarget,
            focusGeneration: focusGeneration,
            executablePath: Bundle.main.executableURL?.path ?? "",
            pngSHA256: pngSHA256,
            cjkOCRMarkers: cjkOCRMarkers
        )
    }

    func waitForOwnedWindow(
        onWaiting: @escaping @MainActor @Sendable () -> Void = {}
    ) async throws {
        let updates = NotificationCenter.default.notifications(
            named: NSApplication.didUpdateNotification,
            object: NSApplication.shared
        )
        onWaiting()
        var count = readinessWindowCount()
        try validateWindowCountForReadiness(count)
        if count == 1 { return }
        for await _ in updates {
            try Task.checkCancellation()
            count = readinessWindowCount()
            try validateWindowCountForReadiness(count)
            if count == 1 { return }
        }
        throw CancellationError()
    }

    private func readinessWindowCount() -> Int {
        injectedWindowIDs?().count ?? windows().count
    }

    private func validateWindowCountForReadiness(_ count: Int) throws {
        if count > 1 {
            throw PackagedWindowCaptureError.windowCount(count)
        }
    }

    public static func windowMetadata(
        _ windowID: CGWindowID
    ) -> PackagedWindowMetadata? {
        guard let rows = CGWindowListCopyWindowInfo(
            [.optionIncludingWindow],
            windowID
        ) as? [[String: Any]],
        let row = rows.first,
        let ownerPID = row[kCGWindowOwnerPID as String] as? pid_t,
        let layer = row[kCGWindowLayer as String] as? Int,
        let rawBounds = row[kCGWindowBounds as String] as? NSDictionary,
        let bounds = CGRect(dictionaryRepresentation: rawBounds)
        else { return nil }
        return PackagedWindowMetadata(
            ownerPID: ownerPID,
            layer: layer,
            bounds: bounds
        )
    }

    public static func windowImage(_ windowID: CGWindowID) -> CGImage? {
        CGWindowListCreateImage(
            .null,
            .optionIncludingWindow,
            windowID,
            [.boundsIgnoreFraming, .bestResolution]
        )
    }

    public static func recognizedCJKMarkers(_ image: CGImage) -> [String] {
        let languageSpecimens = [
            ("ko-KR", ["한국어"]),
            ("ja-JP", ["日本語", "漢字"]),
        ]
        return languageSpecimens.flatMap { pair -> [String] in
            let (language, specimens) = pair
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            request.usesLanguageCorrection = false
            request.recognitionLanguages = [language]
            let handler = VNImageRequestHandler(cgImage: image)
            guard (try? handler.perform([request])) != nil else { return [] }
            let recognized = (request.results ?? [])
                .compactMap { $0.topCandidates(1).first?.string }
                .joined()
            return specimens.filter(recognized.contains)
        }
    }

    private static func hasMeaningfulContent(
        _ image: NSBitmapImageRep
    ) -> Bool {
        var colors = Set<UInt16>()
        let stepX = max(1, image.pixelsWide / 32)
        let stepY = max(1, image.pixelsHigh / 32)
        for y in stride(from: 0, to: image.pixelsHigh, by: stepY) {
            for x in stride(from: 0, to: image.pixelsWide, by: stepX) {
                guard let color = image.colorAt(x: x, y: y)?
                    .usingColorSpace(.deviceRGB) else { continue }
                let red = UInt16((color.redComponent * 15).rounded())
                let green = UInt16((color.greenComponent * 15).rounded())
                let blue = UInt16((color.blueComponent * 15).rounded())
                colors.insert(red << 8 | green << 4 | blue)
                if colors.count >= 8 { return true }
            }
        }
        return false
    }
}
