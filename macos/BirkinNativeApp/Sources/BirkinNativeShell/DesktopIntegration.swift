import BirkinNativeProtocol
import Foundation
import SwiftUI
import UniformTypeIdentifiers

public enum JailedDropState: Equatable, Sendable {
    case idle
    case hovering
    case importing(displayName: String)
    case imported
    case refused(reason: String)
}

public struct ImportedReference: Equatable, Sendable {
    public let importID: String
    public let displayName: String
    public let jailName: String
    public let sha256: String
    public let byteCount: Int

    public var composerToken: String { "[[workspace-import:\(importID)]]" }

    public init?(_ value: NativeJSONValue?) {
        guard case .object(let raw) = value,
              case .string("workspace_import") = raw["kind"],
              case .string(let importID) = raw["import_id"],
              case .string(let displayName) = raw["display_name"],
              case .string(let jailName) = raw["jail_name"],
              case .string(let sha256) = raw["sha256"],
              case .int(let byteCount) = raw["byte_count"],
              !importID.isEmpty, !displayName.isEmpty, !jailName.isEmpty,
              sha256.count == 64, byteCount >= 0 else { return nil }
        self.importID = importID
        self.displayName = displayName
        self.jailName = jailName
        self.sha256 = sha256
        self.byteCount = byteCount
    }

    public var canonicalJSONObject: NativeJSONObject {
        [
            "kind": .string("workspace_import"),
            "import_id": .string(importID),
            "display_name": .string(displayName),
            "jail_name": .string(jailName),
            "sha256": .string(sha256),
            "byte_count": .int(byteCount),
        ]
    }
}

@MainActor
public final class JailedDropModel: ObservableObject {
    @Published public private(set) var state: JailedDropState = .idle
    @Published public private(set) var reference: ImportedReference?

    public init() {}

    public func setHovering(_ hovering: Bool) {
        guard reference == nil else { return }
        state = hovering ? .hovering : .idle
    }

    @discardableResult
    public func accept(
        urls: [URL],
        availability: MutationAvailability,
        expectedCursor: Int,
        session: NativeReadySession,
        submit: (NativeCommandRequest) -> Void
    ) -> Bool {
        guard availability.isEnabled,
              session.supportedCommands.contains("file.import") else {
            state = .refused(reason: availability.disabledReason ?? "Import is not advertised by Python.")
            return false
        }
        guard urls.count == 1, let source = urls.first, source.isFileURL else {
            state = .refused(reason: "Drop a local regular file.")
            return false
        }
        let id = UUID().uuidString.lowercased()
        submit(NativeCommandRequest(
            frameID: "command-\(id)", commandID: id,
            expectedCursor: expectedCursor, commandType: "file.import",
            payload: ["source_path": .string(source.path)],
            sessionCapability: session.sessionCapability, viewID: "composer"
        ))
        reference = nil
        state = .importing(displayName: source.lastPathComponent)
        return true
    }

    /// Show Python's bounded refusal for an import that never completed.
    public func refuse(reason: String) {
        state = .refused(reason: String(reason.prefix(300)))
    }

    public func clearAfterAcceptedSend(importIDs: Set<String>) {
        guard let reference, importIDs.contains(reference.importID) else { return }
        self.reference = nil
        state = .idle
    }

    public func applyCanonicalResult(_ result: NativeJSONObject) {
        guard case .object(let receipt) = result["receipt"],
              case .bool(true) = receipt["copied"],
              let imported = ImportedReference(result["reference"]) else {
            state = .refused(reason: "Python refused the import.")
            return
        }
        reference = imported
        state = .imported
    }
}

public struct ImportedReferenceChip: View {
    public let reference: ImportedReference

    public init(reference: ImportedReference) { self.reference = reference }

    public var body: some View {
        Label(reference.displayName, systemImage: "doc.badge.checkmark")
            .font(.caption)
            .padding(.horizontal, 8)
            .padding(.vertical, 5)
            .background(.quaternary, in: Capsule())
            .accessibilityLabel("Imported file \(reference.displayName)")
    }
}

public struct JailedDropZone: View {
    @ObservedObject private var model: JailedDropModel
    private let acceptURLs: ([URL]) -> Void

    public init(model: JailedDropModel, acceptURLs: @escaping ([URL]) -> Void) {
        self.model = model
        self.acceptURLs = acceptURLs
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let reference = model.reference {
                ImportedReferenceChip(reference: reference)
            } else {
                Label(label, systemImage: "square.and.arrow.down")
                    .font(.caption)
                    .foregroundStyle(model.state == .hovering ? Color.accentColor : .secondary)
            }
            if case .refused(let reason) = model.state {
                Text(reason).font(.caption).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(8)
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .strokeBorder(model.state == .hovering ? Color.accentColor : .secondary.opacity(0.4), style: StrokeStyle(lineWidth: 1, dash: [4]))
        )
        .onDrop(of: [UTType.fileURL.identifier], isTargeted: Binding(
            get: { model.state == .hovering },
            set: { model.setHovering($0) }
        )) { providers in
            guard providers.count == 1, let provider = providers.first else { return false }
            _ = provider.loadObject(ofClass: URL.self) { value, _ in
                guard let url = value else { return }
                Task { @MainActor in acceptURLs([url]) }
            }
            return true
        }
        .accessibilityLabel("Import file into workspace jail")
    }

    private var label: String {
        switch model.state {
        case .idle: NativeLocalization.string("Drop a file to import")
        case .hovering: "Release to copy into workspace"
        case .importing(let name): "Importing \(name)"
        case .imported: "Imported"
        case .refused: "Import refused"
        }
    }
}
