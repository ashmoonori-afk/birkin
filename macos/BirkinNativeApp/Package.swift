// swift-tools-version: 6.0
// The macOS native app package and release executable.

import PackageDescription

let package = Package(
    name: "BirkinNativeApp",
    defaultLocalization: "en",
    platforms: [.macOS(.v13)],
    products: [
        .library(name: "BirkinNativeProtocol", targets: ["BirkinNativeProtocol"]),
        .library(name: "BirkinNativeShell", targets: ["BirkinNativeShell"]),
        .executable(name: "BirkinNativeApp", targets: ["BirkinNativeApp"]),
    ],
    targets: [
        .target(name: "BirkinNativeProtocol"),
        .target(
            name: "BirkinNativeShell",
            dependencies: ["BirkinNativeProtocol"],
            resources: [.process("Resources")]
        ),
        .executableTarget(
            name: "BirkinNativeApp",
            dependencies: ["BirkinNativeProtocol", "BirkinNativeShell"]
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
        .testTarget(
            name: "BirkinNativeAppTests",
            dependencies: ["BirkinNativeApp"]
        ),
    ]
)
