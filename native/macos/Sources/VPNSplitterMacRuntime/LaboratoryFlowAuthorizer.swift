import AuditTokenSupport
import Foundation
import Security
import VPNSplitterCore

public enum LaboratoryFlowDecision: String {
    case directControl
    case blockSelected
    case blockUnknownApplication
    case blockInvalidIdentity
    case blockOtherUser

    public var allowsDirect: Bool { self == .directControl }
}

protocol RunningCodeIdentity {
    var signingIdentifier: String { get }
    func satisfies(_ requirement: SecRequirement) -> Bool
}

private struct SecurityCodeIdentity: RunningCodeIdentity {
    let code: SecCode
    let signingIdentifier: String

    func satisfies(_ requirement: SecRequirement) -> Bool {
        SecCodeCheckValidity(code, SecCSFlags(), requirement) == errSecSuccess
    }

    static func resolve(auditToken: Data) throws -> SecurityCodeIdentity {
        // Only consume tokens supplied by NetworkExtension, never a client-supplied PID.
        let attributes = [kSecGuestAttributeAudit as String: auditToken] as CFDictionary
        var code: SecCode?
        guard SecCodeCopyGuestWithAttributes(nil, attributes, SecCSFlags(), &code) == errSecSuccess,
              let code = code,
              SecCodeCheckValidity(code, SecCSFlags(), nil) == errSecSuccess else {
            throw ConfigurationError.invalid("Cannot validate the flow's running application.")
        }
        var staticCode: SecStaticCode?
        guard SecCodeCopyStaticCode(code, SecCSFlags(), &staticCode) == errSecSuccess,
              let staticCode = staticCode else {
            throw ConfigurationError.invalid("Cannot inspect the running application's signature.")
        }
        let details = try ApplicationInspector.signingInformation(for: staticCode)
        return Self(code: code, signingIdentifier: details.identifier)
    }
}

/// Not a VPN policy: only the explicitly pinned control application may bypass this laboratory.
/// All helpers and unknown identities are rejected inside the laboratory's loopback scope.
public final class LaboratoryFlowAuthorizer {
    private let configuration: LaboratoryConfiguration
    private let blockedRequirement: SecRequirement
    private let directRequirement: SecRequirement
    private let lookup: (Data) throws -> RunningCodeIdentity

    public convenience init(configuration: LaboratoryConfiguration) throws {
        try self.init(configuration: configuration, lookup: SecurityCodeIdentity.resolve)
    }

    init(configuration: LaboratoryConfiguration,
         lookup: @escaping (Data) throws -> RunningCodeIdentity) throws {
        try configuration.validate()
        blockedRequirement = try ApplicationInspector.compileRequirement(
            configuration.blockedApplication.designatedRequirement
        )
        directRequirement = try ApplicationInspector.compileRequirement(
            configuration.directApplication.designatedRequirement
        )
        self.configuration = configuration
        self.lookup = lookup
    }

    public func decision(auditToken: Data?, reportedSigningIdentifier: String) -> LaboratoryFlowDecision {
        guard let token = auditToken else { return .blockInvalidIdentity }
        var uid: uid_t = 0
        let valid = token.withUnsafeBytes {
            vps_audit_token_euid($0.baseAddress, $0.count, &uid)
        }
        guard valid else { return .blockInvalidIdentity }
        guard uid == configuration.ownerUID else { return .blockOtherUser }
        let selected = reportedSigningIdentifier == configuration.blockedApplication.signingIdentifier
        let control = reportedSigningIdentifier == configuration.directApplication.signingIdentifier
        guard selected || control else { return .blockUnknownApplication }
        do {
            let identity = try lookup(token)
            guard identity.signingIdentifier == reportedSigningIdentifier,
                  identity.satisfies(selected ? blockedRequirement : directRequirement) else {
                return .blockInvalidIdentity
            }
            return selected ? .blockSelected : .directControl
        } catch {
            return .blockInvalidIdentity
        }
    }
}
