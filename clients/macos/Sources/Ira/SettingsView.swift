import AppKit
import IraKit
import SwiftUI

final class SettingsState: ObservableObject {
    @Published var recording = false
    var monitor: Any?
    @Published var speak = true
    @Published var onlyFolders: [String] = []
    @Published var extraFolders: [String] = []
    @Published var confirmForget = false
}

struct SettingsView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var conversation: Conversation
    let hotKeyChanged: () -> Void
    @StateObject private var state = SettingsState()

    var body: some View {
        Form {
            Section("This Mac") {
                LabeledContent("Server", value: model.settings.server.isEmpty ? "Not paired" : model.settings.server)
                LabeledContent("Name on Ira", value: model.settings.deviceLabel)
                LabeledContent("Connection", value: AppDelegate.describe(model.deviceState, paired: model.paired))
                LabeledContent("Talking through", value: conversation.transportKind.map { $0 == "live" ? "live voice" : "the HTTP API" } ?? "not connected yet")
                HStack {
                    Button("Reconnect") { model.reconnect() }
                    Button("Pair again…") {
                        Task { await model.forget() }
                    }
                    .help("Remove this Mac from Ira and pair it with a new code")
                    Spacer()
                    Button("Remove this Mac", role: .destructive) { state.confirmForget = true }
                }
            }
            Section("Shortcut") {
                HStack {
                    Text("Open Ira with")
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
                Text("“Hey Ira” without a key comes in a later version.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Voice") {
                Toggle("Speak replies to typed questions too", isOn: $state.speak)
                    .onChange(of: state.speak) { _, on in model.settings.speakReplies = on }
                if let email = model.settings.signedInEmail {
                    HStack {
                        Text("Signed in as \(email) for when live voice is not available")
                            .font(.callout)
                        Spacer()
                        Button("Sign out") { Task { await model.signOut() } }
                    }
                } else {
                    Text("Talking uses this Mac's own key and the server's live voice. On a server without live voice, Ira asks you to sign in once.")
                        .font(.caption).foregroundStyle(.secondary)
                }
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
            Section("Privacy") {
                HStack {
                    Button("Microphone…") { openPrivacy("Privacy_Microphone") }
                    Button("Screen Recording…") { openPrivacy("Privacy_ScreenCapture") }
                    Button("Files and Folders…") { openPrivacy("Privacy_FilesAndFolders") }
                }
                Text("Logs in ~/Library/Logs/Ira hold tool names and timings, never what Ira read or heard.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .onAppear {
            state.speak = model.settings.speakReplies
            state.onlyFolders = model.settings.onlyFolders
            state.extraFolders = model.settings.extraFolders
        }
        .onDisappear(perform: stopRecording)
        .confirmationDialog("Remove this Mac from Ira?", isPresented: $state.confirmForget) {
            Button("Remove", role: .destructive) { Task { await model.forget() } }
        } message: {
            Text("Ira forgets this Mac's key at once. To use Ira here again, pair it with a new code.")
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
