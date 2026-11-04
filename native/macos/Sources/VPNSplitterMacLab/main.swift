import Darwin
import Foundation
import VPNSplitterCore
import VPNSplitterMacRuntime

let usage = """
VPN Splitter macOS laboratory (no network changes)

Usage:
  VPNSplitterMacLab inspect /path/to/Application.app
  VPNSplitterMacLab configuration /path/to/Blocked.app /path/to/Direct.app

inspect validates a bundle's signature and prints its selection metadata as JSON.
configuration validates two distinct signed applications and prints a laboratory
configuration for the current user. The provider's fixed scope is TCP/UDP to
127.0.0.1 and ::1 on port 49600. Helpers are not implicitly authorized.
Neither command installs an extension, connects a VPN or launches applications.
"""

func encode<T: Encodable>(_ value: T) throws {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    let data = try encoder.encode(value)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
}

let arguments = Array(CommandLine.arguments.dropFirst())
do {
    switch arguments.first {
    case nil, "--help", "-h":
        guard arguments.count <= 1 else { throw ConfigurationError.invalid(usage) }
        print(usage)
    case "inspect":
        guard arguments.count == 2 else { throw ConfigurationError.invalid(usage) }
        try encode(ApplicationInspector.inspect(at: URL(fileURLWithPath: arguments[1])))
    case "configuration":
        guard arguments.count == 3 else { throw ConfigurationError.invalid(usage) }
        let blocked = try ApplicationInspector.inspect(at: URL(fileURLWithPath: arguments[1]))
        let direct = try ApplicationInspector.inspect(at: URL(fileURLWithPath: arguments[2]))
        let configuration = LaboratoryConfiguration(ownerUID: getuid(), blockedApplication: blocked,
                                                   directApplication: direct)
        try configuration.validate()
        try encode(configuration)
    default:
        throw ConfigurationError.invalid(usage)
    }
} catch {
    fputs("macOS laboratory: \(error.localizedDescription)\n", stderr)
    exit(1)
}
