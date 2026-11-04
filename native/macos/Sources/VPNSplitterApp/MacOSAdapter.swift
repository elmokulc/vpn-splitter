import AppKit
import VPNSplitterCore
import VPNSplitterMacRuntime

enum MacOSAdapter {
    static func inspectApplication(at selectedURL: URL) throws -> SelectedApplication {
        try ApplicationInspector.inspect(at: selectedURL)
    }

    static var diagnostics: [String] {
        #if arch(arm64)
        let architecture = "Native arm64 build (Apple Silicon target)."
        #else
        let architecture = "Non-arm64 build. Rebuild natively on Apple Silicon."
        #endif
        let paths = ["/opt/homebrew/bin/openconnect", "/opt/homebrew/sbin/openconnect"]
        let openconnect = paths.first { FileManager.default.isExecutableFile(atPath: $0) }
        return [
            architecture,
            "macOS: \(ProcessInfo.processInfo.operatingSystemVersionString)",
            openconnect.map { "OpenConnect found: \($0) (transport not connected)." }
                ?? "OpenConnect not found in the standard Apple Silicon Homebrew paths.",
            "Network Extension: not installed by this preview.",
            "No applications are protected. Host networking is unchanged.",
        ]
    }
}
