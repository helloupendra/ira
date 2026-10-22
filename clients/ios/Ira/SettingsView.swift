import IraPhoneKit
import SwiftUI

/// This iPhone's pairing and connection, the checklist, what Ira used here, and
/// removing the iPhone from Ira.
struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var confirmingRemoval = false

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
                                .foregroundStyle(item.ok ? Color.green : Color.orange)
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
