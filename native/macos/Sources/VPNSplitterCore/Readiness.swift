/// Capabilities must be established by the macOS adapter and validated on a Mac.
/// Finding OpenConnect or saving a profile never implies network protection.
public enum NetworkCapability: String, CaseIterable {
    case flowSelection = "Application and helper identification"
    case vpnTransport = "OpenConnect TCP/UDP relay"
    case privateDNS = "Private per-application VPN DNS"
    case ipv6Protection = "IPv6 tunnel or blocking"
    case failureProtection = "Protection across worker and extension failures"
    case signedInstallation = "Signed Network Extension installation"
}

public struct DevelopmentBackend {
    public init() {}
    public var canConnect: Bool { false }
    public var applicationsProtected: Bool { false }
    public var missingCapabilities: [NetworkCapability] { NetworkCapability.allCases }

    public func connect(profile: MacProfile) throws {
        try profile.validate()
        throw ConfigurationError.invalid(
            "The macOS network adapter is not implemented. No applications are protected."
        )
    }
}
