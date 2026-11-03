// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "VPNSplitterMac",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "VPNSplitterPreview", targets: ["VPNSplitterApp"]),
        .library(name: "VPNSplitterCore", targets: ["VPNSplitterCore"]),
    ],
    targets: [
        .target(name: "VPNSplitterCore"),
        .executableTarget(name: "VPNSplitterApp", dependencies: ["VPNSplitterCore"]),
        .testTarget(name: "VPNSplitterCoreTests", dependencies: ["VPNSplitterCore"]),
    ]
)
