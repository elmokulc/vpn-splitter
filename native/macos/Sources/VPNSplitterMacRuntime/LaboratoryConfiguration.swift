import Foundation
import VPNSplitterCore

/// A separate format from VPN profiles. This experiment only targets numeric loopback addresses.
public struct LaboratoryConfiguration: Codable, Equatable {
    public static let port = "49600"
    public static let addresses = ["127.0.0.1", "::1"]
    public let schemaVersion: Int
    public let ownerUID: UInt32
    public let blockedApplication: SelectedApplication
    public let directApplication: SelectedApplication

    public init(ownerUID: UInt32, blockedApplication: SelectedApplication,
                directApplication: SelectedApplication) {
        schemaVersion = 1
        self.ownerUID = ownerUID
        self.blockedApplication = blockedApplication
        self.directApplication = directApplication
    }

    public func validate() throws {
        guard schemaVersion == 1, ownerUID > 0, ownerUID < UInt32.max - 1 else {
            throw ConfigurationError.invalid("Invalid laboratory schema or user account.")
        }
        try blockedApplication.validate()
        try directApplication.validate()
        guard blockedApplication.path != directApplication.path,
              blockedApplication.signingIdentifier != directApplication.signingIdentifier else {
            throw ConfigurationError.invalid("Choose two applications with distinct signing identities.")
        }
    }

    public static func decode(_ data: Data) throws -> LaboratoryConfiguration {
        guard data.count <= 128 * 1024,
              let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(object.keys) == ["schemaVersion", "ownerUID", "blockedApplication", "directApplication"] else {
            throw ConfigurationError.invalid("Invalid laboratory configuration fields or size.")
        }
        let keys: Set<String> = ["name", "path", "signingIdentifier", "designatedRequirement"]
        for key in ["blockedApplication", "directApplication"] {
            guard let application = object[key] as? [String: Any], Set(application.keys) == keys else {
                throw ConfigurationError.invalid("Invalid laboratory application fields.")
            }
        }
        let configuration = try JSONDecoder().decode(Self.self, from: data)
        try configuration.validate()
        return configuration
    }
}
