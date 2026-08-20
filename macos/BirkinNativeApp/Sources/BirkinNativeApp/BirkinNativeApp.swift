import BirkinNativeProtocol
import BirkinNativeShell
import SwiftUI

public enum BirkinApplicationConfiguration {
    public static let bundleIdentifier = "com.birkin.native"
    public static let version = "0.4.242"
    public static let build = "1"
    public static let windowTitle = "Birkin"
}

@main
struct BirkinNativeApplication: App {
    private let store = NativeProjectionStore()

    var body: some Scene {
        WindowGroup(BirkinApplicationConfiguration.windowTitle) {
            NativeShellView(store: store, connectionState: .disconnected)
                .frame(minWidth: 960, minHeight: 640)
        }
        .defaultSize(width: 1280, height: 800)
    }
}
