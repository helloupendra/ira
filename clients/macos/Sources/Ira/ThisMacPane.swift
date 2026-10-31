import AppKit
import IraKit
import SwiftUI

/// This Mac in the window: which Ira it is paired with and as which device, the connection,
/// the skills your Ira has on for it, macOS's permissions with a way to fix each, and what
/// Ira used here lately.
struct ThisMacPane: View {
    @ObservedObject var model: AppModel
    @ObservedObject var conversation: Conversation
    @ObservedObject var permissions: PermissionCenter

    init(model: AppModel, conversation: Conversation) {
        self.model = model
        self.conversation = conversation
        self.permissions = model.permissions
    }

    var body: some View {
        Form {
            Section("Your Ira") {
                LabeledContent("Paired with", value: model.settings.server.isEmpty ? "Not paired" : model.settings.server)
                LabeledContent("This Mac on it", value: deviceName)
                LabeledContent("Connection") {
                    HStack(spacing: 6) {
                        Circle().fill(statusColor).frame(width: 8, height: 8)
                        Text(AppDelegate.describe(model.deviceState, paired: model.paired))
                    }
                }
                if let kind = conversation.transportKind {
                    LabeledContent("Questions go through", value: kind == "live" ? "live voice" : "the HTTP API (typed answers)")
                }
                if !conversation.permissions.isEmpty {
                    LabeledContent("This Mac may", value: conversation.permissions.map(SettingsView.permissionName).joined(separator: ", "))
                }
                HStack {
                    Button("Reconnect") { model.reconnect() }
                    Button("Pair again…") {
                        model.startRepair()
                        NotificationCenter.default.post(name: .iraShowPanel, object: nil)
                    }
                    .help("Pair with a new code. This Mac's current pairing stays until the new one works.")
                    Spacer()
                }
            }
            Section {
                if skills.isEmpty {
                    Text("None yet. Switch skills on for this Mac in Your devices on your Ira, with your PIN.")
                        .foregroundStyle(.secondary)
                }
                ForEach(skills, id: \.self) { skill in
                    Label {
                        Text(ThisMacPane.title(skill)).foregroundStyle(Presence.ink)
                    } icon: {
                        Image(systemName: ThisMacPane.symbol(skill)).foregroundStyle(Presence.green)
                    }
                }
                if let devices = devicesPage {
                    Button("Change them in Your devices…") { NSWorkspace.shared.open(devices) }
                }
            } header: {
                Text("Skills on for this Mac")
            } footer: {
                Text("Ira uses a skill only when you ask, and only if macOS allows it below.")
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            Section("Permissions") {
                ForEach(permissions.all) { permission in
                    PermissionRow(
                        permission: permission,
                        ask: { Task { await permissions.ask(permission) } },
                        open: { permissions.open(permission) })
                }
                Button("Check again") { permissions.refresh() }
            }
            if model.approvals.banner != nil {
                Section("Using this Mac for you") {
                    ApprovalBanner(approvals: model.approvals)
                }
            }
            Section("What I read") {
                if model.activity.isEmpty {
                    Text("Nothing yet. Ira reads only when you ask.").foregroundStyle(.secondary)
                }
                ForEach(model.activity.prefix(20)) { entry in
                    HStack(alignment: .firstTextBaseline) {
                        Image(systemName: entry.ok ? "checkmark" : "xmark")
                            .foregroundStyle(entry.ok ? Color.secondary : Color.red)
                            .font(.caption)
                        Text("\(entry.verb): \(entry.target)")
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Spacer()
                        Text(entry.at, style: .time)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .formStyle(.grouped)
        .scrollContentBackground(.hidden)
        .background(Presence.bg)
        .navigationTitle("This Mac")
        .onAppear { permissions.refresh() }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            permissions.refresh()
        }
    }

    private var deviceName: String {
        let label = model.settings.deviceLabel.isEmpty ? "This Mac" : model.settings.deviceLabel
        return model.settings.deviceID.map { "\(label) (device \($0))" } ?? label
    }

    private var skills: [String] {
        if case .connected(_, let skills) = model.deviceState { return skills }
        return []
    }

    /// Your devices on your Ira's web app.
    private var devicesPage: URL? {
        model.settings.server.isEmpty ? nil : URL(string: model.settings.server + "/#panel=devices")
    }

    private var statusColor: Color {
        switch model.deviceState {
        case .connected: return .green
        case .connecting, .waiting: return .orange
        case .refused, .stopped, .keyUnavailable: return .red
        }
    }

    static func title(_ skill: String) -> String {
        switch skill {
        case "files": return "Files: find, read and open them"
        case "screen": return "Screen: read the window you were in"
        case "browser": return "Browser: your tabs"
        case "clipboard": return "Clipboard: what you copied"
        case "apps": return "Apps and links: open them"
        case "control": return "Control: type, click and scroll, after your PIN"
        case "shortcuts": return "Shortcuts: list and run them"
        case "mail": return "Mail: search and draft"
        case "notes": return "Notes: search and add"
        case "calendar": return "Calendar"
        case "reminders": return "Reminders"
        case "contacts": return "Contacts"
        case "messages": return "Messages: send after your yes"
        case "tasks": return "Coding tasks"
        case "routine": return "Routine: when this Mac locks, sleeps and wakes"
        default: return skill.capitalized
        }
    }

    static func symbol(_ skill: String) -> String {
        switch skill {
        case "files": return "folder"
        case "screen": return "macwindow"
        case "browser": return "safari"
        case "clipboard": return "doc.on.clipboard"
        case "apps": return "square.grid.2x2"
        case "control": return "cursorarrow.click"
        case "shortcuts": return "square.stack.3d.up"
        case "mail": return "envelope"
        case "notes": return "note.text"
        case "calendar": return "calendar"
        case "reminders": return "checklist"
        case "contacts": return "person.crop.circle"
        case "messages": return "message"
        case "tasks": return "hammer"
        case "routine": return "clock.arrow.circlepath"
        default: return "puzzlepiece"
        }
    }
}
