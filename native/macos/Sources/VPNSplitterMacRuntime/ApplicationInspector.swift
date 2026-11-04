import Foundation
import Security
import VPNSplitterCore

public enum ApplicationInspector {
    public static func inspect(at selectedURL: URL) throws -> SelectedApplication {
        let url = selectedURL.resolvingSymlinksInPath().standardizedFileURL
        guard url.pathExtension == "app", let bundle = Bundle(url: url),
              let executable = bundle.executableURL,
              FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw ConfigurationError.invalid("Select a macOS application bundle with an executable.")
        }
        let code = try staticCode(at: url)
        let flags = SecCSFlags(rawValue: kSecCSStrictValidate | kSecCSCheckAllArchitectures)
        guard SecStaticCodeCheckValidity(code, flags, nil) == errSecSuccess else {
            throw ConfigurationError.invalid("The application's code signature is not valid.")
        }
        let details = try signingInformation(for: code)
        var requirement: SecRequirement?
        var text: CFString?
        guard SecCodeCopyDesignatedRequirement(code, SecCSFlags(), &requirement) == errSecSuccess,
              let requirement = requirement,
              SecRequirementCopyString(requirement, SecCSFlags(), &text) == errSecSuccess,
              let text = text else {
            throw ConfigurationError.invalid("Cannot read the application's signing requirement.")
        }
        let app = SelectedApplication(
            name: bundle.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String
                ?? bundle.object(forInfoDictionaryKey: "CFBundleName") as? String
                ?? url.deletingPathExtension().lastPathComponent,
            path: url.path, signingIdentifier: details.identifier,
            designatedRequirement: text as String
        )
        try app.validate()
        return app
    }

    /// Recheck the stored requirement, rather than silently trusting a replacement at the same path.
    public static func revalidate(_ application: SelectedApplication) throws {
        try application.validate()
        let current = try inspect(at: URL(fileURLWithPath: application.path))
        guard current.path == application.path,
              current.signingIdentifier == application.signingIdentifier else {
            throw ConfigurationError.invalid("The selected application's identity or path has changed.")
        }
        let requirement = try compileRequirement(application.designatedRequirement)
        let code = try staticCode(at: URL(fileURLWithPath: application.path))
        let flags = SecCSFlags(rawValue: kSecCSStrictValidate | kSecCSCheckAllArchitectures)
        guard SecStaticCodeCheckValidity(code, flags, requirement) == errSecSuccess else {
            throw ConfigurationError.invalid("The application no longer satisfies its saved signing requirement.")
        }
    }

    static func compileRequirement(_ text: String) throws -> SecRequirement {
        var requirement: SecRequirement?
        guard SecRequirementCreateWithString(text as CFString, SecCSFlags(), &requirement) == errSecSuccess,
              let requirement = requirement else {
            throw ConfigurationError.invalid("Invalid application signing requirement.")
        }
        return requirement
    }

    static func signingInformation(for code: SecStaticCode) throws -> (identifier: String, certificates: [SecCertificate]) {
        var information: CFDictionary?
        guard SecCodeCopySigningInformation(code, SecCSFlags(rawValue: kSecCSSigningInformation),
                                           &information) == errSecSuccess,
              let details = information as? [String: Any],
              let identifier = details[kSecCodeInfoIdentifier as String] as? String,
              !identifier.isEmpty,
              let certificates = details[kSecCodeInfoCertificates as String] as? [SecCertificate],
              !certificates.isEmpty else {
            throw ConfigurationError.invalid("Unsigned and ad-hoc signed applications are unsupported.")
        }
        return (identifier, certificates)
    }

    private static func staticCode(at url: URL) throws -> SecStaticCode {
        var code: SecStaticCode?
        guard SecStaticCodeCreateWithPath(url as CFURL, SecCSFlags(), &code) == errSecSuccess,
              let code = code else {
            throw ConfigurationError.invalid("Cannot inspect this application's signature.")
        }
        return code
    }
}
