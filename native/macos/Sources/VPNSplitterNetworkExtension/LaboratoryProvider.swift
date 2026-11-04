import Foundation
import NetworkExtension
import VPNSplitterCore
import VPNSplitterMacRuntime

protocol LaboratoryFlow {
    var auditToken: Data? { get }
    var signingIdentifier: String { get }
    func denyRead(_ error: Error)
    func denyWrite(_ error: Error)
}

extension NEAppProxyFlow: LaboratoryFlow {
    var auditToken: Data? { metaData.sourceAppAuditToken }
    var signingIdentifier: String { metaData.sourceAppSigningIdentifier }
    func denyRead(_ error: Error) { closeReadWithError(error) }
    func denyWrite(_ error: Error) { closeWriteWithError(error) }
}

enum LaboratoryFlowRouter {
    static func handle(_ flow: LaboratoryFlow, gate: LaboratoryFlowGate) -> Bool {
        let decision = gate.decision(auditToken: flow.auditToken,
                                     reportedSigningIdentifier: flow.signingIdentifier)
        if decision.allowsDirect {
            // In a transparent proxy, false explicitly allows a direct connection.
            return false
        }
        let error = NSError(domain: NSPOSIXErrorDomain, code: Int(EACCES))
        flow.denyRead(error)
        flow.denyWrite(error)
        return true
    }
}

public enum LaboratoryNetworkSettings {
    public static func make() -> NETransparentProxyNetworkSettings {
        let settings = NETransparentProxyNetworkSettings(tunnelRemoteAddress: "127.0.0.1")
        settings.includedNetworkRules = zip(LaboratoryConfiguration.addresses, [32, 128]).map { address, prefix in
            NENetworkRule(
                remoteNetwork: NWHostEndpoint(hostname: address, port: LaboratoryConfiguration.port),
                remotePrefix: prefix, localNetwork: nil, localPrefix: 0,
                protocol: .any, direction: .outbound
            )
        }
        settings.excludedNetworkRules = []
        // No default route, DNS settings, transport or production traffic interception.
        return settings
    }
}

/// Compilable laboratory provider, deliberately absent from the preview app bundle.
public final class LaboratoryProvider: NETransparentProxyProvider {
    private let gate = LaboratoryFlowGate()

    public override func startProxy(options: [String: Any]? = nil,
                                    completionHandler: @escaping (Error?) -> Void) {
        let attempt = gate.beginStart()
        do {
            guard let configuration = protocolConfiguration as? NETunnelProviderProtocol,
                  let fields = configuration.providerConfiguration,
                  Set(fields.keys) == ["laboratoryConfiguration"],
                  let data = fields["laboratoryConfiguration"] as? Data else {
                throw ConfigurationError.invalid("A bounded laboratory configuration is required.")
            }
            let policy = try LaboratoryFlowAuthorizer(configuration: LaboratoryConfiguration.decode(data))
            setTunnelNetworkSettings(LaboratoryNetworkSettings.make()) { error in
                let current = self.gate.completeStart(attempt, authorizer: error == nil ? policy : nil)
                completionHandler(error ?? (current ? nil : ConfigurationError.invalid("Laboratory start was cancelled.")))
            }
        } catch {
            gate.completeStart(attempt, authorizer: nil)
            completionHandler(error)
        }
    }

    public override func stopProxy(with reason: NEProviderStopReason,
                                   completionHandler: @escaping () -> Void) {
        gate.stop()
        completionHandler()
    }

    public override func handleNewFlow(_ flow: NEAppProxyFlow) -> Bool {
        LaboratoryFlowRouter.handle(flow, gate: gate)
    }

    // Both UDP callback variants default to handleNewFlow; TCP and UDP share one decision path.
}
