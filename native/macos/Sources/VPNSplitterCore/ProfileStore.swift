import Foundation

public struct ProfileStore {
    public let directory: URL
    public var file: URL { directory.appendingPathComponent("profiles.json") }

    public init(directory: URL) {
        self.directory = directory
    }

    private struct Document: Codable {
        let schemaVersion: Int
        let profiles: [MacProfile]
    }

    public func load() throws -> [MacProfile] {
        guard FileManager.default.fileExists(atPath: file.path) else { return [] }
        let data = try Data(contentsOf: file)
        guard data.count <= 4 * 1024 * 1024 else {
            throw ConfigurationError.invalid("The profile file is too large.")
        }
        try validateKeys(in: data)
        let document = try JSONDecoder().decode(Document.self, from: data)
        guard document.schemaVersion == 1 else {
            throw ConfigurationError.invalid("Unsupported macOS profile format.")
        }
        try validate(document.profiles)
        return document.profiles
    }

    public func save(_ profiles: [MacProfile]) throws {
        try validate(profiles)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(Document(schemaVersion: 1, profiles: profiles))
        guard data.count <= 4 * 1024 * 1024 else {
            throw ConfigurationError.invalid("The profile file is too large.")
        }
        try FileManager.default.createDirectory(
            at: directory, withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        // Atomic replacement prevents a partially written configuration after a crash.
        // Restrict the containing directory before creating even the temporary file.
        try FileManager.default.setAttributes([.posixPermissions: 0o700],
                                             ofItemAtPath: directory.path)
        try data.write(to: file, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600],
                                             ofItemAtPath: file.path)
    }

    private func validate(_ profiles: [MacProfile]) throws {
        guard profiles.count <= 100, Set(profiles.map(\.id)).count == profiles.count else {
            throw ConfigurationError.invalid("Too many profiles or duplicate profile identifiers.")
        }
        for profile in profiles { try profile.validate() }
    }

    private func validateKeys(in data: Data) throws {
        guard let document = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(document.keys) == ["schemaVersion", "profiles"],
              let profiles = document["profiles"] as? [[String: Any]] else {
            throw ConfigurationError.invalid("Invalid macOS profile document.")
        }
        let profileKeys: Set<String> = [
            "id", "name", "server", "username", "authgroup", "cafile", "applications",
        ]
        let appKeys: Set<String> = ["name", "path", "signingIdentifier", "designatedRequirement"]
        for profile in profiles {
            guard Set(profile.keys) == profileKeys,
                  let apps = profile["applications"] as? [[String: Any]],
                  apps.allSatisfy({ Set($0.keys) == appKeys }) else {
                throw ConfigurationError.invalid("Unknown or missing profile fields. Secrets are not supported.")
            }
        }
    }
}
