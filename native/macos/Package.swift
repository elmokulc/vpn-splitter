// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "VPNSplitterMac",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "VPNSplitterPreview", targets: ["VPNSplitterApp"]),
        .library(name: "VPNSplitterCore", targets: ["VPNSplitterCore"]),
        .executable(name: "VPNSplitterMacLab", targets: ["VPNSplitterMacLab"]),
        .executable(name: "VPNSplitterNetworkLab", targets: ["VPNSplitterNetworkLab"]),
    ],
    targets: [
        .target(name: "VPNSplitterCore"),
        .target(name: "AuditTokenSupport", linkerSettings: [.linkedLibrary("bsm")]),
        .target(name: "VPNSplitterMacRuntime", dependencies: ["VPNSplitterCore", "AuditTokenSupport"]),
        .target(name: "VPNSplitterNetworkExtension", dependencies: ["VPNSplitterCore", "VPNSplitterMacRuntime"]),
        .executableTarget(name: "VPNSplitterMacLab", dependencies: ["VPNSplitterCore", "VPNSplitterMacRuntime"]),
        .executableTarget(name: "VPNSplitterNetworkLab", dependencies: ["VPNSplitterNetworkExtension"]),
        .executableTarget(name: "VPNSplitterApp", dependencies: ["VPNSplitterCore", "VPNSplitterMacRuntime"]),
        .testTarget(name: "VPNSplitterCoreTests", dependencies: ["VPNSplitterCore"]),
        .testTarget(
            name: "VPNSplitterMacRuntimeTests",
            dependencies: ["VPNSplitterCore", "VPNSplitterMacRuntime", "VPNSplitterNetworkExtension", "AuditTokenSupport"]
        ),
    ]
)
