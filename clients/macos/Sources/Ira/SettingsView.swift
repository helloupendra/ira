import AppKit
import IraKit
import SwiftUI

final class SettingsState: ObservableObject {
    @Published var recording = false
    var monitor: Any?
    @Published var speak = true
    @Published var wake = false
    @Published var login = false
    @Published var loginProblem: String?
    @Published var onlyFolders: [String] = []
    @Published var extraFolders: [String] = []
    @Published var confirmRemove = false
    @Published var confirmRepair = false
}

struct SettingsView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var conversation: Conversation
    @ObservedObject var permissions: PermissionCenter
    let hotKeyChanged: () -> Void
    @StateObject private var state = SettingsState()

    init(model: AppModel, conversation: Conversation, hotKeyChanged: @escaping () -> Void) {
        self.model = model
        self.conversation = conversation
        self.permissions = model.permissions
        self.hotKeyChanged = hotKeyChanged
    }

    var body: some View {
        Form {
            Section("This Mac") {
                LabeledContent("Your Ira", value: model.settings.server.isEmpty ? "Not paired" : model.settings.server)
                LabeledContent("Name on Ira", value: model.settings.deviceLabel)
                LabeledContent("Connection", value: AppDelegate.describe(model.deviceState, paired: model.paired))
                LabeledContent("Talking through", value: conversation.transportKind.map { $0 == "live" ? "live voice" : "the HTTP API" } ?? "not connected yet")
                if !conversation.permissions.isEmpty {
                    LabeledContent("This Mac may", value: conversation.permissions.map(Self.permissionName).joined(separator: ", "))
                }
                HStack {
                    Button("Reconnect") { model.reconnect() }
                    Button("Pair again…") { state.confirmRepair = true }
                    Spacer()
                }
            }
            Section("Open Ira") {
                HStack {
                    Text("Shortcut")
                    Spacer()
                    Button(state.recording ? "Press the new keys…" : HotKey.describe(keyCode: model.settings.hotKeyCode, modifiers: model.settings.hotKeyModifiers)) {
                        state.recording ? stopRecording() : startRecording()
                    }
                    Button("Reset") {
                        model.settings.hotKeyCode = 49
                        model.settings.hotKeyModifiers = 0x0800
                        hotKeyChanged()
                    }
                }
                Toggle("Open Ira when I log in", isOn: $state.login)
                    .onChange(of: state.login) { _, on in
                        guard on != LoginItem.enabled else { return }
                        state.loginProblem = LoginItem.set(on)
                    }
                if let problem = state.loginProblem {
                    Text(problem).font(.caption).foregroundStyle(.orange)
                }
            }
            Section("“\(model.wake.phrase)”") {
                Toggle("Listen for “\(model.wake.phrase)”", isOn: $state.wake)
                    .onChange(of: state.wake) { _, on in
                        guard on != model.settings.wakeWord || on != model.wakeListening else { return }
                        Task {
                            await model.setWakeWord(on)
                            state.wake = model.settings.wakeWord
                        }
                    }
                Text("The Mac listens for the phrase by itself, with speech recognition on this Mac; nothing leaves it until it hears the phrase. The menu-bar mark shows a dot while it listens. Off by default.")
                    .font(.caption).foregroundStyle(.secondary)
                if let problem = model.wakeProblem {
                    Text(problem).font(.caption).foregroundStyle(.orange)
                }
            }
            Section("Voice") {
                Toggle("Speak replies to typed questions too", isOn: $state.speak)
                    .onChange(of: state.speak) { _, on in model.settings.speakReplies = on }
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
            Section("Folders") {
                Text("Ira finds and reads files in your home folder, never in ~/Library, keychains or hidden folders. Choose folders below to narrow it, or to add a drive.")
                    .font(.caption).foregroundStyle(.secondary)
                FolderList(title: "Only these folders (empty: the whole home folder)", folders: $state.onlyFolders) {
                    model.settings.onlyFolders = state.onlyFolders
                }
                FolderList(title: "Also these folders outside the home folder", folders: $state.extraFolders) {
                    model.settings.extraFolders = state.extraFolders
                }
            }
            Section("Coding tasks") {
                Text(model.tasksConfigured
                     ? "Set up: Ira can start coding tasks in the repositories listed in tasks.json."
                     : "Not set up. To let Ira start coding tasks, list your repositories and the agent's command in tasks.json (see Ira for Mac's guide).")
                    .font(.callout)
                HStack {
                    Button("Show tasks.json") {
                        let folder = TaskSettings.defaultPath.deletingLastPathComponent()
                        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                        NSWorkspace.shared.open(folder)
                    }
                    Button("Reload tools") { model.reloadTools() }
                        .help("Tell Ira this Mac's tools again, after changing tasks.json")
                }
            }
            Section("Privacy") {
                Text("Logs in ~/Library/Logs/Ira hold tool names and timings, never what Ira read or heard.")
                    .font(.caption).foregroundStyle(.secondary)
                HStack {
                    Button("Show Logs") {
                        if let logs = IraLog.defaultDirectory { NSWorkspace.shared.open(logs) }
                    }
                    Spacer()
                    Button("Remove Ira from this Mac…", role: .destructive) { state.confirmRemove = true }
                }
            }
        }
        .formStyle(.grouped)
        .onAppear {
            state.speak = model.settings.speakReplies
            state.wake = model.settings.wakeWord
            state.login = LoginItem.enabled
            state.onlyFolders = model.settings.onlyFolders
            state.extraFolders = model.settings.extraFolders
            permissions.refresh()
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            permissions.refresh()
        }
        .onDisappear(perform: stopRecording)
        .confirmationDialog("Remove Ira from this Mac?", isPresented: $state.confirmRemove) {
            Button("Remove", role: .destructive) {
                Task {
                    await model.removeEverything()
                    NSApp.keyWindow?.close()
                }
            }
        } message: {
            Text("Your Ira forgets this Mac at once, and the app deletes its key, settings and logs here. Your files are not touched. Then drag Ira from Applications to the Bin.")
        }
        .confirmationDialog("Pair this Mac again?", isPresented: $state.confirmRepair) {
            Button("Pair again", role: .destructive) { Task { await model.removeEverything() } }
        } message: {
            Text("This Mac's current pairing ends at once. Then make a new pairing code on Your devices.")
        }
    }

    static func permissionName(_ permission: String) -> String {
        switch permission {
        case "ask": return "talk to Ira"
        case "voice": return "use voice"
        case "actions": return "confirm actions with your PIN"
        default: return permission
        }
    }

    private func startRecording() {
        state.recording = true
        state.monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            let modifiers = HotKey.carbonModifiers(event.modifierFlags)
            if event.keyCode == 53 && modifiers == 0 {  // Esc: keep the old one
                stopRecording()
                return nil
            }
            guard modifiers != 0 else { return nil }
            model.settings.hotKeyCode = UInt32(event.keyCode)
            model.settings.hotKeyModifiers = modifiers
            hotKeyChanged()
            stopRecording()
            return nil
        }
    }

    private func stopRecording() {
        if let monitor = state.monitor { NSEvent.removeMonitor(monitor) }
        state.monitor = nil
        state.recording = false
    }
}

struct FolderList: View {
    let title: String
    @Binding var folders: [String]
    let changed: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.callout)
            ForEach(folders, id: \.self) { folder in
                HStack {
                    Image(systemName: "folder")
                    Text(folder).lineLimit(1).truncationMode(.middle)
                    Spacer()
                    Button {
                        folders.removeAll { $0 == folder }
                        changed()
                    } label: {
                        Image(systemName: "minus.circle")
                    }
                    .buttonStyle(.borderless)
                }
            }
            Button("Add a folder…") {
                let panel = NSOpenPanel()
                panel.canChooseDirectories = true
                panel.canChooseFiles = false
                panel.allowsMultipleSelection = false
                if panel.runModal() == .OK, let url = panel.url, !folders.contains(url.path) {
                    folders.append(url.path)
                    changed()
                }
            }
        }
    }
}
