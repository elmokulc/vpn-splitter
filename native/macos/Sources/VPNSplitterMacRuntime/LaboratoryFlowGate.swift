import Foundation

/// Serializes start/stop with flow decisions; an old completion cannot revive a stopped policy.
public final class LaboratoryFlowGate {
    private let lock = NSLock()
    private var pendingAttempt: UUID?
    private var authorizer: LaboratoryFlowAuthorizer?

    public init() {}

    public func beginStart() -> UUID {
        lock.lock()
        defer { lock.unlock() }
        let attempt = UUID()
        pendingAttempt = attempt
        authorizer = nil
        return attempt
    }

    @discardableResult
    public func completeStart(_ attempt: UUID, authorizer: LaboratoryFlowAuthorizer?) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard pendingAttempt == attempt else { return false }
        pendingAttempt = nil
        self.authorizer = authorizer
        return true
    }

    public func stop() {
        lock.lock()
        defer { lock.unlock() }
        pendingAttempt = nil
        authorizer = nil
    }

    public func decision(auditToken: Data?, reportedSigningIdentifier: String) -> LaboratoryFlowDecision {
        lock.lock()
        defer { lock.unlock() }
        return authorizer?.decision(auditToken: auditToken, reportedSigningIdentifier: reportedSigningIdentifier)
            ?? .blockInvalidIdentity
    }
}
