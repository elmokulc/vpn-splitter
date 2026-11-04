import Foundation
import NetworkExtension
import VPNSplitterNetworkExtension

// A raw SwiftPM executable is not an installable or entitled system extension.
// Refuse manual execution: activation belongs to a separately signed containing app.
guard Bundle.main.bundleURL.pathExtension == "systemextension" else {
    fputs("This laboratory provider must be packaged and signed as a Network Extension.\n", stderr)
    exit(1)
}
autoreleasepool {
    NEProvider.startSystemExtensionMode()
}
dispatchMain()
