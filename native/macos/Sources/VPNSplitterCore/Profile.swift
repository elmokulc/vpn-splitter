import Foundation

public enum ConfigurationError: Error, LocalizedError {
    case invalid(String)

    public var errorDescription: String? {
        switch self {
        case .invalid(let message): return message
        }
    }
}

private func validateText(_ value: String, label: String, limit: Int) throws {
    guard value.count <= limit,
          !value.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) })
    else { throw ConfigurationError.invalid("Invalid \(label).") }
}

/// A selection records a validated signature, not just an editable bundle identifier.
/// Runtime flow/helper identity verification is still required by the future adapter.
public struct SelectedApplication: Codable, Equatable, Identifiable {
    public var id: String { path }
    public let name: String
    public let path: String
    public let signingIdentifier: String
    public let designatedRequirement: String

    public init(name: String, path: String, signingIdentifier: String,
                designatedRequirement: String) {
        self.name = name
        self.path = path
        self.signingIdentifier = signingIdentifier
        self.designatedRequirement = designatedRequirement
    }

    public func validate() throws {
        try validateText(name, label: "application name", limit: 256)
        try validateText(path, label: "application path", limit: 4096)
        try validateText(signingIdentifier, label: "signing identifier", limit: 512)
        try validateText(designatedRequirement, label: "signature requirement", limit: 16384)
        guard !name.isEmpty, path.hasPrefix("/"), path.hasSuffix(".app"),
              !signingIdentifier.isEmpty, !designatedRequirement.isEmpty
        else { throw ConfigurationError.invalid("Select a signed .app bundle using Add application.") }
    }
}

/// No password, OTP or authentication cookie is represented in this format.
public struct MacProfile: Codable, Equatable, Identifiable {
    public var id: UUID
    public var name: String
    public var server: String
    public var username: String
    public var authgroup: String
    public var cafile: String
    public var applications: [SelectedApplication]

    public init(id: UUID = UUID(), name: String = "", server: String = "",
                username: String = "", authgroup: String = "", cafile: String = "",
                applications: [SelectedApplication] = []) {
        self.id = id
        self.name = name
        self.server = server
        self.username = username
        self.authgroup = authgroup
        self.cafile = cafile
        self.applications = applications
    }

    public func validate() throws {
        try validateText(name, label: "profile name", limit: 120)
        try validateText(server, label: "VPN address", limit: 2048)
        try validateText(username, label: "username", limit: 256)
        try validateText(authgroup, label: "group", limit: 256)
        try validateText(cafile, label: "CA certificate path", limit: 4096)
        guard !name.trimmingCharacters(in: .whitespaces).isEmpty else {
            throw ConfigurationError.invalid("Enter a profile name.")
        }
        guard !server.unicodeScalars.contains(where: { CharacterSet.whitespaces.contains($0) }),
              let url = URLComponents(string: server), url.scheme == "https",
              let host = url.host, !host.isEmpty,
              url.user == nil, url.password == nil, url.query == nil, url.fragment == nil,
              url.port.map({ (1...65535).contains($0) }) ?? true
        else {
            throw ConfigurationError.invalid(
                "Use an HTTPS VPN address without credentials, a query or a fragment."
            )
        }
        guard cafile.isEmpty || cafile.hasPrefix("/") else {
            throw ConfigurationError.invalid("The CA certificate path must be absolute.")
        }
        guard applications.count <= 100,
              Set(applications.map(\.path)).count == applications.count
        else { throw ConfigurationError.invalid("Too many applications or duplicate selections.") }
        for app in applications { try app.validate() }
    }
}
