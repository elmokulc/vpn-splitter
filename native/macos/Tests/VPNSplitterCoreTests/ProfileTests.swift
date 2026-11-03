import Foundation
import XCTest
@testable import VPNSplitterCore

final class ProfileTests: XCTestCase {
    private func profile(server: String = "https://vpn.example.test") -> MacProfile {
        MacProfile(name: "Work", server: server, username: "alice", authgroup: "staff")
    }

    func testRejectsCredentialBearingAndInsecureGatewayAddresses() {
        for server in [
            "http://vpn.test", "https://alice:secret@vpn.test", "https://vpn.test?cookie=x",
            "https://vpn.test#fragment", "https://vpn.test\n", "https://vpn.test:99999",
            "https://vpn.test:0", "--script=bad", "https://", "https://vpn.test/a b",
        ] {
            XCTAssertThrowsError(try profile(server: server).validate(), server)
        }
        XCTAssertNoThrow(try profile(server: "https://vpn.test:443/group").validate())
        XCTAssertNoThrow(try profile(server: "https://[2001:db8::1]/group").validate())
    }

    func testRejectsRelativeCertificatesAndControlCharacters() {
        var item = profile()
        item.cafile = "relative.pem"
        XCTAssertThrowsError(try item.validate())
        item.cafile = "/tmp/ca.pem"
        item.username = "alice\u{0}"
        XCTAssertThrowsError(try item.validate())
        item.username = "alice"
        item.name = "   "
        XCTAssertThrowsError(try item.validate())
    }

    func testApplicationSelectionRequiresSignatureMetadataAndNoDuplicatePaths() {
        let app = SelectedApplication(name: "Browser", path: "/Applications/Browser.app",
                                      signingIdentifier: "test.browser",
                                      designatedRequirement: "identifier test.browser")
        var item = profile()
        item.applications = [app]
        XCTAssertNoThrow(try item.validate())
        item.applications.append(app)
        XCTAssertThrowsError(try item.validate())
        XCTAssertThrowsError(try SelectedApplication(
            name: "Unsigned", path: "/Applications/Unsigned.app",
            signingIdentifier: "", designatedRequirement: ""
        ).validate())
    }

    func testStoreRoundTripHasPrivatePermissionsAndNoSecretFields() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = ProfileStore(directory: directory)
        XCTAssertEqual(try store.load(), [])
        let item = profile()
        try store.save([item])
        XCTAssertEqual(try store.load(), [item])
        let data = try Data(contentsOf: store.file)
        let document = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let profiles = try XCTUnwrap(document["profiles"] as? [[String: Any]])
        XCTAssertEqual(Set(profiles[0].keys),
                       ["id", "name", "server", "username", "authgroup", "cafile", "applications"])
        let fileMode = try FileManager.default.attributesOfItem(atPath: store.file.path)[.posixPermissions] as? NSNumber
        let directoryMode = try FileManager.default.attributesOfItem(atPath: directory.path)[.posixPermissions] as? NSNumber
        XCTAssertEqual(fileMode?.intValue, 0o600)
        XCTAssertEqual(directoryMode?.intValue, 0o700)
    }

    func testInvalidSavePreservesPreviouslySavedProfiles() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = ProfileStore(directory: directory)
        let item = profile()
        try store.save([item])
        let original = try Data(contentsOf: store.file)
        XCTAssertThrowsError(try store.save([item, item]))
        XCTAssertThrowsError(try store.save([profile(server: "http://insecure.test")]))
        XCTAssertEqual(try Data(contentsOf: store.file), original)
    }

    func testLoadRejectsFutureSchemasSecretFieldsAndCorruptionWithoutRewriting() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = ProfileStore(directory: directory)
        try store.save([profile()])
        let data = try Data(contentsOf: store.file)
        var document = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        document["schemaVersion"] = 2
        let future = try JSONSerialization.data(withJSONObject: document)
        try future.write(to: store.file)
        XCTAssertThrowsError(try store.load())
        XCTAssertEqual(try Data(contentsOf: store.file), future)
        document["schemaVersion"] = 1
        var profiles = try XCTUnwrap(document["profiles"] as? [[String: Any]])
        profiles[0]["password"] = "not-a-real-secret"
        document["profiles"] = profiles
        try JSONSerialization.data(withJSONObject: document).write(to: store.file)
        XCTAssertThrowsError(try store.load())
        try Data("{broken".utf8).write(to: store.file)
        XCTAssertThrowsError(try store.load())
    }

    func testPreviewCannotConnectOrClaimProtectionEvenWithAValidProfile() {
        let backend = DevelopmentBackend()
        XCTAssertFalse(backend.canConnect)
        XCTAssertFalse(backend.applicationsProtected)
        XCTAssertEqual(Set(backend.missingCapabilities), Set(NetworkCapability.allCases))
        XCTAssertThrowsError(try backend.connect(profile: profile()))
    }
}
