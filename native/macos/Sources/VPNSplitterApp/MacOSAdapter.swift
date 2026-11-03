import AppKit
import Security
import VPNSplitterCore

enum MacOSAdapter {
    static func inspectApplication(at selectedURL: URL) throws -> SelectedApplication {
        let url = selectedURL.resolvingSymlinksInPath().standardizedFileURL
        guard url.pathExtension == "app", let bundle = Bundle(url: url),
              bundle.executableURL != nil else {
            throw ConfigurationError.invalid("Select a macOS application bundle.")
        }
        var code: SecStaticCode?
        guard SecStaticCodeCreateWithPath(url as CFURL, SecCSFlags(), &code) == errSecSuccess,
              let code = code else {
            throw ConfigurationError.invalid("Cannot inspect this application's signature.")
        }
        // Signature metadata alone is not validation. Validate before reading it.
        let flags = SecCSFlags(rawValue: kSecCSStrictValidate | kSecCSCheckAllArchitectures)
        guard SecStaticCodeCheckValidity(code, flags, nil) == errSecSuccess else {
            throw ConfigurationError.invalid("The application's code signature is not valid.")
        }
        var information: CFDictionary?
        guard SecCodeCopySigningInformation(code, SecCSFlags(rawValue: kSecCSSigningInformation),
                                           &information) == errSecSuccess,
              let details = information as? [String: Any],
              let identifier = details[kSecCodeInfoIdentifier as String] as? String,
              let certificates = details[kSecCodeInfoCertificates as String] as? [SecCertificate],
              !certificates.isEmpty else {
            throw ConfigurationError.invalid("Unsigned and ad-hoc signed applications are unsupported.")
        }
        var requirement: SecRequirement?
        var requirementText: CFString?
        guard SecCodeCopyDesignatedRequirement(code, SecCSFlags(), &requirement) == errSecSuccess,
              let requirement = requirement,
              SecRequirementCopyString(requirement, SecCSFlags(), &requirementText) == errSecSuccess,
              let requirementText = requirementText else {
            throw ConfigurationError.invalid("Cannot read the application's signing requirement.")
        }
        let app = SelectedApplication(
            name: bundle.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String
                ?? bundle.object(forInfoDictionaryKey: "CFBundleName") as? String
                ?? url.deletingPathExtension().lastPathComponent,
            path: url.path, signingIdentifier: identifier,
            designatedRequirement: requirementText as String
        )
        try app.validate()
        return app
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
