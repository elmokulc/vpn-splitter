import Foundation
import XCTest
import VPNSplitterCore
import VPNSplitterMacRuntime

final class ApplicationInspectorTests: XCTestCase {
    private func systemApplication() throws -> SelectedApplication {
        let url = URL(fileURLWithPath: "/System/Applications/TextEdit.app")
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw XCTSkip("TextEdit is not installed on this macOS test host")
        }
        return try ApplicationInspector.inspect(at: url)
    }

    func testSystemApplicationHasValidatedSignatureAndCanBeRevalidated() throws {
        let application = try systemApplication()
        XCTAssertFalse(application.signingIdentifier.isEmpty)
        XCTAssertFalse(application.designatedRequirement.isEmpty)
        XCTAssertNoThrow(try ApplicationInspector.revalidate(application))
    }

    func testSavedRequirementAndSigningIdentifierCannotBeSilentlyReplaced() throws {
        let application = try systemApplication()
        let wrongRequirement = SelectedApplication(
            name: application.name, path: application.path, signingIdentifier: application.signingIdentifier,
            designatedRequirement: "identifier \"org.vpnsplitter.nonexistent\""
        )
        XCTAssertThrowsError(try ApplicationInspector.revalidate(wrongRequirement))
        let wrongIdentifier = SelectedApplication(
            name: application.name, path: application.path, signingIdentifier: "org.vpnsplitter.nonexistent",
            designatedRequirement: application.designatedRequirement
        )
        XCTAssertThrowsError(try ApplicationInspector.revalidate(wrongIdentifier))
    }

    func testMissingExecutableAndStandaloneExecutableAreRejected() throws {
        XCTAssertThrowsError(try ApplicationInspector.inspect(at: URL(fileURLWithPath: "/usr/bin/true")))
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let bundle = directory.appendingPathComponent("Empty.app/Contents")
        try FileManager.default.createDirectory(at: bundle, withIntermediateDirectories: true)
        let plist: [String: String] = ["CFBundleIdentifier": "test.empty", "CFBundleExecutable": "Missing"]
        try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0)
            .write(to: bundle.appendingPathComponent("Info.plist"))
        XCTAssertThrowsError(try ApplicationInspector.inspect(at: bundle.deletingLastPathComponent()))
    }

    func testAdHocSignedBundleIsRejected() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let app = directory.appendingPathComponent("AdHoc.app")
        let contents = app.appendingPathComponent("Contents")
        let executable = contents.appendingPathComponent("MacOS/Fixture")
        try FileManager.default.createDirectory(at: executable.deletingLastPathComponent(), withIntermediateDirectories: true)
        try FileManager.default.copyItem(at: URL(fileURLWithPath: "/usr/bin/true"), to: executable)
        let plist: [String: String] = [
            "CFBundleIdentifier": "test.adhoc", "CFBundleExecutable": "Fixture", "CFBundlePackageType": "APPL",
        ]
        try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0)
            .write(to: contents.appendingPathComponent("Info.plist"))
        let signer = Process()
        signer.executableURL = URL(fileURLWithPath: "/usr/bin/codesign")
        signer.arguments = ["--force", "--sign", "-", app.path]
        signer.standardOutput = FileHandle.nullDevice
        signer.standardError = FileHandle.nullDevice
        try signer.run()
        signer.waitUntilExit()
        XCTAssertEqual(signer.terminationStatus, 0)
        XCTAssertThrowsError(try ApplicationInspector.inspect(at: app))
    }
}
