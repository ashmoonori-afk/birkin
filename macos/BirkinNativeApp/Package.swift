// swift-tools-version: 6.0
// The macOS native app package. Wave 4.1 ships the protocol library and its
// tests only; the application target arrives in a later wave.

import PackageDescription

let package = Package(
    name: "BirkinNativeApp",
    platforms: [.macOS(.v13)],
    products: [
        .library(name: "BirkinNativeProtocol", targets: ["BirkinNativeProtocol"]),
        .library(name: "BirkinNativeShell", targets: ["BirkinNativeShell"]),
    ],
    targets: [
        .target(name: "BirkinNativeProtocol"),
        .target(
            name: "BirkinNativeShell",
            dependencies: ["BirkinNativeProtocol"]
        ),
        .testTarget(
            name: "BirkinNativeProtocolTests",
            dependencies: ["BirkinNativeProtocol", "BirkinNativeShell"],
            resources: [.copy("GoldenVectors")]
        ),
        .testTarget(
            name: "BirkinNativeShellTests",
            dependencies: ["BirkinNativeShell", "BirkinNativeProtocol"]
        ),
    ]
)
