import AuditTokenSupport
import Darwin
import Foundation
import NetworkExtension
import Security
import XCTest
import VPNSplitterCore
@testable import VPNSplitterMacRuntime
@testable import VPNSplitterNetworkExtension

final class LaboratoryTests: XCTestCase {
    private func application(_ identifier: String) -> SelectedApplication {
        SelectedApplication(name: identifier, path: "/Applications/\(identifier).app",
                            signingIdentifier: identifier,
                            designatedRequirement: "identifier \"\(identifier)\"")
    }

    private func configuration(uid: UInt32 = getuid()) -> LaboratoryConfiguration {
        LaboratoryConfiguration(ownerUID: uid, blockedApplication: application("test.blocked"),
                                directApplication: application("test.direct"))
    }

    private func ownToken() throws -> Data {
        var data = Data(count: vps_audit_token_size())
        let copied = data.withUnsafeMutableBytes { vps_copy_own_audit_token($0.baseAddress, $0.count) }
        XCTAssertTrue(copied)
        return data
    }

    private struct Code: RunningCodeIdentity {
        let signingIdentifier: String
        var valid = true
        func satisfies(_ requirement: SecRequirement) -> Bool { valid }
    }

    func testAuditTokenParserRejectsMalformedLengthsAndReadsKernelUserIdentity() throws {
        var uid: uid_t = UInt32.max
        for count in [0, 1, Int(vps_audit_token_size()) - 1, Int(vps_audit_token_size()) + 1] {
            XCTAssertFalse(Data(count: count).withUnsafeBytes {
                vps_audit_token_euid($0.baseAddress, $0.count, &uid)
            })
            XCTAssertEqual(uid, UInt32.max)
        }
        let token = try ownToken()
        XCTAssertTrue(token.withUnsafeBytes { vps_audit_token_euid($0.baseAddress, $0.count, &uid) })
        XCTAssertEqual(uid, geteuid())
    }

    func testSelectedApplicationNeverFallsBackToDirectNetworking() throws {
        let policy = try LaboratoryFlowAuthorizer(configuration: configuration()) { _ in
            Code(signingIdentifier: "test.blocked")
        }
        let decision = policy.decision(auditToken: try ownToken(), reportedSigningIdentifier: "test.blocked")
        XCTAssertEqual(decision, .blockSelected)
        XCTAssertFalse(decision.allowsDirect)
    }

    func testOnlyExplicitControlIdentityWithValidRequirementIsDirect() throws {
        let policy = try LaboratoryFlowAuthorizer(configuration: configuration()) { _ in
            Code(signingIdentifier: "test.direct")
        }
        XCTAssertEqual(policy.decision(auditToken: try ownToken(), reportedSigningIdentifier: "test.direct"), .directControl)
        XCTAssertEqual(policy.decision(auditToken: try ownToken(), reportedSigningIdentifier: "test.direct.helper"), .blockUnknownApplication)
        XCTAssertEqual(policy.decision(auditToken: try ownToken(), reportedSigningIdentifier: "unknown"), .blockUnknownApplication)
    }

    func testMissingTokenWrongUserAndMalformedTokenAreRejectedBeforeCodeLookup() throws {
        let policy = try LaboratoryFlowAuthorizer(configuration: configuration(uid: getuid() + 1)) { _ in
            XCTFail("Invalid caller must not reach code lookup")
            return Code(signingIdentifier: "test.direct")
        }
        XCTAssertEqual(policy.decision(auditToken: nil, reportedSigningIdentifier: "test.direct"), .blockInvalidIdentity)
        XCTAssertEqual(policy.decision(auditToken: Data([0]), reportedSigningIdentifier: "test.direct"), .blockInvalidIdentity)
        XCTAssertEqual(policy.decision(auditToken: try ownToken(), reportedSigningIdentifier: "test.direct"), .blockOtherUser)
    }

    func testClaimedIdentifierMismatchedRequirementAndExitedProcessCannotAuthorizeDirect() throws {
        let token = try ownToken()
        for identity in [Code(signingIdentifier: "test.blocked"), Code(signingIdentifier: "test.direct", valid: false)] {
            let policy = try LaboratoryFlowAuthorizer(configuration: configuration()) { _ in identity }
            XCTAssertEqual(policy.decision(auditToken: token, reportedSigningIdentifier: "test.direct"), .blockInvalidIdentity)
        }
        let policy = try LaboratoryFlowAuthorizer(configuration: configuration()) { _ in
            throw ConfigurationError.invalid("Process no longer exists")
        }
        XCTAssertEqual(policy.decision(auditToken: token, reportedSigningIdentifier: "test.direct"), .blockInvalidIdentity)
    }

    func testRealSecurityLookupDoesNotTrustClaimedControlIdentifier() throws {
        let policy = try LaboratoryFlowAuthorizer(configuration: configuration())
        // The test runner's actual kernel token is not the claimed control application's identity.
        XCTAssertEqual(policy.decision(auditToken: try ownToken(), reportedSigningIdentifier: "test.direct"), .blockInvalidIdentity)
    }

    func testStartupFailureStopAndStaleCompletionCannotEnableDirectControl() throws {
        let gate = LaboratoryFlowGate()
        let token = try ownToken()
        let policy = try LaboratoryFlowAuthorizer(configuration: configuration()) { _ in
            Code(signingIdentifier: "test.direct")
        }
        func decision() -> LaboratoryFlowDecision {
            gate.decision(auditToken: token, reportedSigningIdentifier: "test.direct")
        }
        XCTAssertFalse(decision().allowsDirect)
        let first = gate.beginStart()
        XCTAssertFalse(decision().allowsDirect)
        XCTAssertTrue(gate.completeStart(first, authorizer: policy))
        XCTAssertTrue(decision().allowsDirect)
        let second = gate.beginStart()
        XCTAssertFalse(decision().allowsDirect)
        XCTAssertFalse(gate.completeStart(first, authorizer: policy))
        XCTAssertTrue(gate.completeStart(second, authorizer: nil))
        XCTAssertFalse(decision().allowsDirect)
        let third = gate.beginStart()
        gate.stop()
        XCTAssertFalse(gate.completeStart(third, authorizer: policy))
        XCTAssertFalse(decision().allowsDirect)
    }

    func testProviderFlowHandlingClosesBothDirectionsAndNeverReturnsDirectForSelectedOrUnknownCode() throws {
        final class Flow: LaboratoryFlow {
            let auditToken: Data?
            let signingIdentifier: String
            var readError: NSError?
            var writeError: NSError?
            init(token: Data?, identifier: String) {
                auditToken = token
                signingIdentifier = identifier
            }
            func denyRead(_ error: Error) { readError = error as NSError }
            func denyWrite(_ error: Error) { writeError = error as NSError }
        }
        let gate = LaboratoryFlowGate()
        let token = try ownToken()
        for identifier in ["test.blocked", "unknown", "test.direct"] {
            let policy = try LaboratoryFlowAuthorizer(configuration: configuration()) { _ in
                Code(signingIdentifier: identifier)
            }
            gate.completeStart(gate.beginStart(), authorizer: policy)
            let flow = Flow(token: token, identifier: identifier)
            let handled = LaboratoryFlowRouter.handle(flow, gate: gate)
            if identifier == "test.direct" {
                XCTAssertFalse(handled)
                XCTAssertNil(flow.readError)
                XCTAssertNil(flow.writeError)
            } else {
                XCTAssertTrue(handled)
                XCTAssertEqual(flow.readError?.domain, NSPOSIXErrorDomain)
                XCTAssertEqual(flow.readError?.code, Int(EACCES))
                XCTAssertEqual(flow.writeError?.code, Int(EACCES))
            }
        }
        gate.stop()
        let flow = Flow(token: token, identifier: "test.direct")
        XCTAssertTrue(LaboratoryFlowRouter.handle(flow, gate: gate))
        XCTAssertNotNil(flow.readError)
        XCTAssertNotNil(flow.writeError)
    }

    func testConfigurationRejectsRootDuplicateIdentitiesInvalidRequirementsAndSecretFields() throws {
        XCTAssertThrowsError(try configuration(uid: 0).validate())
        let duplicate = LaboratoryConfiguration(ownerUID: getuid(), blockedApplication: application("same"),
                                                directApplication: application("same"))
        XCTAssertThrowsError(try duplicate.validate())
        let invalid = SelectedApplication(name: "Invalid", path: "/Applications/Invalid.app",
                                          signingIdentifier: "invalid", designatedRequirement: "not valid syntax !!!")
        XCTAssertThrowsError(try LaboratoryFlowAuthorizer(configuration: LaboratoryConfiguration(
            ownerUID: getuid(), blockedApplication: invalid, directApplication: application("test.direct")
        )))
        let encoder = JSONEncoder()
        let data = try encoder.encode(configuration())
        XCTAssertEqual(try LaboratoryConfiguration.decode(data), configuration())
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        object["password"] = "not-a-real-password"
        XCTAssertThrowsError(try LaboratoryConfiguration.decode(JSONSerialization.data(withJSONObject: object)))
        object.removeValue(forKey: "password")
        object["schemaVersion"] = 2
        XCTAssertThrowsError(try LaboratoryConfiguration.decode(JSONSerialization.data(withJSONObject: object)))
        object["schemaVersion"] = 1
        var app = try XCTUnwrap(object["directApplication"] as? [String: Any])
        app["cookie"] = "not-a-real-cookie"
        object["directApplication"] = app
        XCTAssertThrowsError(try LaboratoryConfiguration.decode(JSONSerialization.data(withJSONObject: object)))
        XCTAssertThrowsError(try LaboratoryConfiguration.decode(Data(repeating: 32, count: 128 * 1024 + 1)))
    }

    func testNetworkRulesAreLimitedToLoopbackTCPUDPOnOneNonDNSPort() throws {
        let settings = LaboratoryNetworkSettings.make()
        let rules = try XCTUnwrap(settings.includedNetworkRules)
        XCTAssertEqual(rules.count, 2)
        for (rule, address) in zip(rules, LaboratoryConfiguration.addresses) {
            XCTAssertEqual(rule.matchRemoteEndpoint?.hostname, address)
            XCTAssertEqual(rule.matchRemoteEndpoint?.port, "49600")
            XCTAssertEqual(rule.matchRemotePrefix, address == "::1" ? 128 : 32)
            XCTAssertNil(rule.matchLocalNetwork)
            XCTAssertEqual(rule.matchProtocol, .any)
            XCTAssertEqual(rule.matchDirection, .outbound)
        }
        XCTAssertNil(settings.dnsSettings)
        XCTAssertNil(settings.proxySettings)
    }
}
