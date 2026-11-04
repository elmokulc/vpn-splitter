import AppKit
import SwiftUI
import UniformTypeIdentifiers
import VPNSplitterCore
import VPNSplitterMacRuntime

@MainActor
final class WorkspaceModel: ObservableObject {
    @Published private(set) var profiles: [MacProfile] = []
    @Published var error: String?
    private let store: ProfileStore
    private var loadFailed = false

    init() {
        let support = FileManager.default.urls(for: .applicationSupportDirectory,
                                               in: .userDomainMask)[0]
        store = ProfileStore(directory: support.appendingPathComponent("VPN Splitter"))
        do {
            profiles = try store.load()
        } catch {
            loadFailed = true
            self.error = "Cannot load profiles. The original file is preserved. \(error.localizedDescription)"
        }
    }

    func save(_ profile: MacProfile) -> Bool {
        var updated = profiles.filter { $0.id != profile.id }
        updated.append(profile)
        updated.sort { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
        return persist(updated)
    }

    func delete(_ id: UUID) -> Bool {
        persist(profiles.filter { $0.id != id })
    }

    private func persist(_ updated: [MacProfile]) -> Bool {
        guard !loadFailed else {
            error = "Saving is disabled after a load error. Back up and repair profiles.json, then reopen the app."
            return false
        }
        do {
            try store.save(updated)
            profiles = updated
            return true
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }
}

@main
@MainActor
struct VPNSplitterApp: App {
    @StateObject private var model = WorkspaceModel()

    var body: some Scene {
        Window("VPN Splitter — macOS Preview", id: "main") {
            WorkspaceView(model: model)
                .frame(minWidth: 900, minHeight: 650)
        }
        .defaultSize(width: 1000, height: 760)
    }
}

@MainActor
private struct WorkspaceView: View {
    @ObservedObject var model: WorkspaceModel
    @State private var selection: UUID?
    @State private var draft = MacProfile()
    @State private var showDiagnostics = false
    @State private var checkingApplications = false
    @State private var verificationResults: [String: String] = [:]
    private let backend = DevelopmentBackend()

    var body: some View {
        NavigationSplitView {
            List(model.profiles, selection: $selection) { profile in
                VStack(alignment: .leading) {
                    Text(profile.name).font(.headline)
                    Text(profile.server).font(.caption).foregroundStyle(.secondary)
                }
                .tag(profile.id)
            }
            .navigationTitle("VPN profiles")
            .toolbar {
                Button {
                    selection = nil
                    draft = MacProfile()
                } label: {
                    Label("New profile", systemImage: "plus")
                }
            }
            .navigationSplitViewColumnWidth(min: 200, ideal: 240)
        } detail: {
            Form {
                Section {
                    Label("Configuration preview — no network protection", systemImage: "wrench.and.screwdriver")
                        .font(.headline)
                    Text("Save VPN settings and application selections. Connection and protected launch are unavailable in this development build.")
                        .foregroundStyle(.secondary)
                }
                Section("Connection profile") {
                    TextField("Profile name", text: $draft.name)
                    TextField("HTTPS VPN address", text: $draft.server)
                    TextField("Username (optional)", text: $draft.username)
                    TextField("VPN group (optional)", text: $draft.authgroup)
                    HStack {
                        TextField("CA certificate path (optional)", text: $draft.cafile)
                        Button("Choose…", action: chooseCA)
                    }
                    Text("Passwords and OTPs are never stored in profiles.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Section("Selected applications") {
                    if draft.applications.isEmpty {
                        Text("Add signed .app bundles to prepare your selection.")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(draft.applications) { app in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(app.name)
                                Text(app.path).font(.caption).foregroundStyle(.secondary)
                                Text(app.signingIdentifier).font(.caption).textSelection(.enabled)
                                if let result = verificationResults[app.path] {
                                    Text(result).font(.caption).textSelection(.enabled)
                                }
                            }
                            Spacer()
                            Button("Remove") { draft.applications.removeAll { $0.id == app.id } }
                        }
                    }
                    HStack {
                        Button("Add application…", action: chooseApplication)
                        Button(checkingApplications ? "Verifying…" : "Verify saved identities",
                               action: verifyApplications)
                            .disabled(checkingApplications || draft.applications.isEmpty)
                    }
                    Text("Verification checks current files against saved signatures. It does not provide network protection.")
                        .font(.caption).foregroundStyle(.secondary)
                    Text("A saved selection does not protect the app or its helpers. Runtime signature checks and separate browser instances still require implementation.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Section {
                    HStack {
                        Button("Save profile") {
                            if model.save(draft) {
                                selection = draft.id
                            }
                        }
                        .keyboardShortcut("s", modifiers: .command)
                        if selection != nil {
                            Button("Delete profile", role: .destructive) {
                                if let id = selection, model.delete(id) {
                                    selection = nil
                                    draft = MacProfile()
                                }
                            }
                        }
                        if model.profiles.contains(draft) {
                            Text("Saved").foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("Connect (unavailable)") {
                            do {
                                try backend.connect(profile: draft)
                            } catch {
                                model.error = error.localizedDescription
                            }
                        }
                        .disabled(!backend.canConnect)
                    }
                }
                DisclosureGroup("Network implementation remaining") {
                    ForEach(backend.missingCapabilities, id: \.self) { capability in
                        Label(capability.rawValue, systemImage: "circle.dashed")
                    }
                }
                Button("Show diagnostics") { showDiagnostics = true }
            }
            .formStyle(.grouped)
        }
        .onChange(of: selection) { id in
            if let profile = model.profiles.first(where: { $0.id == id }) {
                draft = profile
            }
        }
        .onChange(of: draft.applications) { _ in verificationResults = [:] }
        .alert("VPN Splitter", isPresented: Binding(
            get: { model.error != nil }, set: { if !$0 { model.error = nil } }
        )) {
            Button("OK") { model.error = nil }
        } message: {
            Text(model.error ?? "")
        }
        .sheet(isPresented: $showDiagnostics) {
            VStack(alignment: .leading, spacing: 16) {
                Text("macOS development diagnostics").font(.title2)
                ForEach(MacOSAdapter.diagnostics, id: \.self) { Text($0).textSelection(.enabled) }
                Button("Done") { showDiagnostics = false }
                    .keyboardShortcut(.defaultAction)
            }
            .padding(24).frame(minWidth: 550)
        }
    }

    private func chooseApplication() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.applicationBundle]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.directoryURL = URL(fileURLWithPath: "/Applications", isDirectory: true)
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            let application = try MacOSAdapter.inspectApplication(at: url)
            guard !draft.applications.contains(where: { $0.path == application.path }) else { return }
            draft.applications.append(application)
        } catch {
            model.error = error.localizedDescription
        }
    }

    private func chooseCA() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        draft.cafile = url.path
    }

    private func verifyApplications() {
        let applications = draft.applications
        checkingApplications = true
        verificationResults = [:]
        Task {
            let results = await Task.detached(priority: .userInitiated) {
                var results: [String: String] = [:]
                for application in applications {
                    do {
                        try ApplicationInspector.revalidate(application)
                        results[application.path] = "Saved signing identity verified."
                    } catch {
                        results[application.path] = "Verification failed: \(error.localizedDescription)"
                    }
                }
                return results
            }.value
            checkingApplications = false
            if applications == draft.applications { verificationResults = results }
        }
    }
}
