import IraPhoneKit
import SwiftUI

/// This iPhone's pairing and connection, the checklist, what Ira used here, and
/// removing the iPhone from Ira.
struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var confirmingRemoval = false
    /// The microphone test: the step running now, and what each step found.
    @State private var testing: String?
    @State private var tested: [MicProbeStep] = []

    var body: some View {
        NavigationStack {
            List {
                Section("Your Ira") {
                    LabeledContent("Address", value: model.settings.server.isEmpty ? "Not paired" : model.settings.server)
                    LabeledContent("This iPhone", value: model.settings.deviceLabel)
                    LabeledContent("Tools", value: connection)
                    if let info = model.info {
                        LabeledContent("Calls", value: info.live ? "Live calls" : "Phone mode")
                        Text(TalkMode.choose(info).explanation)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
                Section {
                    if !model.talk.micReport.isEmpty {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Last call")
                            Text(model.talk.micReport)
                                .font(.footnote.monospaced())
                                .foregroundStyle(.secondary)
                                .textSelection(.enabled)
                        }
                        .accessibilityIdentifier("mic-report")
                    }
                    Button(testing.map { "Testing: \($0)…" } ?? "Test the microphone") {
                        Task { await testMicrophone() }
                    }
                    .disabled(testing != nil || model.talk.inCall)
                    .accessibilityIdentifier("mic-test")
                    ForEach(tested, id: \.name) { step in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(step.name)
                                Spacer()
                                Text(step.verdict)
                                    .foregroundStyle(step.verdict == "sound" ? Presence.green : Presence.warn)
                            }
                            Text(step.line)
                                .font(.caption.monospaced())
                                .foregroundStyle(.secondary)
                                .textSelection(.enabled)
                        }
                    }
                } header: {
                    Text("Microphone")
                } footer: {
                    Text("Talk while the test runs, about ten seconds. It tries the microphone a few ways and says which ones hear you.")
                }
                Section {
                    Picker("Appearance", selection: Binding(get: { model.look }, set: { model.look = $0 })) {
                        Text("System").tag("system")
                        Text("Light").tag("light")
                        Text("Dark").tag("dark")
                    }
                    .pickerStyle(.segmented)
                    .accessibilityIdentifier("appearance")
                } header: {
                    Text("Appearance")
                } footer: {
                    Text("System follows the iPhone's own light or dark look.")
                }
                Section {
                    Button("Get Ira ready…") {
                        dismiss()
                        model.showingSetup = true
                    }
                    Button("Open iPhone Settings for Ira") { model.openSettings() }
                } footer: {
                    Text("Each skill also needs switching on for this iPhone on Your devices, in the Ira web app, with your PIN.")
                }
                Section("What Ira used on this iPhone") {
                    if model.activity.isEmpty {
                        Text("Nothing yet.").foregroundStyle(.secondary)
                    }
                    ForEach(model.activity) { item in
                        HStack {
                            Image(systemName: item.ok ? "checkmark.circle" : "xmark.circle")
                                .foregroundStyle(item.ok ? Presence.green : Presence.warn)
                            Text(item.verb)
                            Spacer()
                            Text(item.at, style: .time).foregroundStyle(.secondary)
                        }
                        .font(.callout)
                    }
                }
                Section {
                    Button("Remove this iPhone from Ira", role: .destructive) { confirmingRemoval = true }
                        .disabled(model.pairing == .unpaired)
                } footer: {
                    Text("Your Ira forgets this iPhone at once (its key stops working), and this iPhone forgets its key and your Ira's address.")
                }
                Section {
                    LabeledContent("Version", value: IraPhone.version)
                }
            }
            .scrollContentBackground(.hidden)
            .background(Presence.bg)
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .confirmationDialog("Remove this iPhone from Ira?", isPresented: $confirmingRemoval, titleVisibility: .visible) {
                Button("Remove", role: .destructive) {
                    Task {
                        await model.removeThisIPhone()
                        dismiss()
                    }
                }
            }
        }
    }

    private func testMicrophone() async {
        if model.permissions.state(.microphone) != .allowed,
            await model.permissions.request(.microphone) != .allowed
        {
            tested = []
            model.notice = "Ira cannot hear you: the microphone is off for Ira. Switch it on in the iPhone's Settings, Ira, Microphone."
            return
        }
        tested = []
        testing = "starting"
        tested = await MicProbe.run { testing = $0 }
        testing = nil
    }

    private var connection: String {
        switch model.deviceState {
        case .connected(_, let skills):
            return skills.isEmpty ? "Connected, no skills on" : "Connected: " + skills.joined(separator: ", ")
        case .connecting: return "Connecting…"
        case .waiting: return "Offline, trying again"
        case .refused: return "Removed on Your devices"
        case .keyUnavailable: return "Key unreadable until unlocked"
        case .stopped: return "Off while Ira is closed"
        }
    }
}
