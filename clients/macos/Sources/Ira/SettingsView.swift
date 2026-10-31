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
    @Published var confirmRepair = false
}

struct SettingsView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var conversation: Conversation
    let hotKeyChanged: () -> Void
    @StateObject private var state = SettingsState()

    init(model: AppModel, conversation: Conversation, hotKeyChanged: @escaping () -> Void) {
        self.model = model
        self.conversation = conversation
        self.hotKeyChanged = hotKeyChanged
    }

    var body: some View {
        Form {
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
            Section("Using this Mac for you") {
                Text("With the Control skill on, a PIN on one step lets Ira do the next steps of that task without asking, for a while (you choose how long in your Ira's Your assistant page). Sending, paying, deleting and pushing still ask every time.")
                    .font(.caption).foregroundStyle(.secondary)
                ApprovalBanner(approvals: model.approvals)
                TrustedAppsRow(approvals: model.approvals)
                if EnclaveApprovalKey.available {
                    TouchIDSetup(model: model)
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
            Section("Logs and removing Ira") {
                Text("Logs in ~/Library/Logs/Ira hold tool names and timings, never what Ira read or heard.")
                    .font(.caption).foregroundStyle(.secondary)
                HStack {
                    Button("Show Logs") {
                        if let logs = IraLog.defaultDirectory { NSWorkspace.shared.open(logs) }
                    }
                    Spacer()
                    // Asks first, then your Ira forgets this Mac, its key and settings go, and Ira quits.
                    Button("Remove Ira from this Mac…", role: .destructive) {
                        (NSApp.delegate as? AppDelegate)?.removeFromMac()
                    }
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
        }
        .onDisappear(perform: stopRecording)

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

final class TouchIDState: ObservableObject {
    @Published var pin = ""
    @Published var working = false
    @Published var answer: String?
    @Published var enrolled = false
}

/// Approving with Touch ID instead of typing the PIN: set up once, with the PIN.
struct TouchIDSetup: View {
    @ObservedObject var model: AppModel
    @StateObject private var state = TouchIDState()

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if state.enrolled {
                HStack {
                    Label("Touch ID approves for this Mac", systemImage: "touchid")
                    Spacer()
                    Button("Turn Off") { run { await model.removeTouchID() } }
                        .disabled(state.working)
                }
            } else {
                Text("Approve with Touch ID instead of your PIN: type your PIN once to set it up. The key stays in this Mac's Secure Enclave and works only after your fingerprint.")
                    .font(.caption).foregroundStyle(.secondary)
                HStack {
                    SecureField("Your PIN", text: $state.pin)
                        .textFieldStyle(.roundedBorder)
                        .frame(maxWidth: 140)
                    Button(state.working ? "Setting up…" : "Set Up Touch ID") {
                        let pin = state.pin
                        state.pin = ""
                        run { await model.enrolTouchID(pin: pin) }
                    }
                    .disabled(state.working || state.pin.count < 4)
                }
            }
            if let answer = state.answer {
                Text(answer).font(.caption)
            }
        }
        .onAppear { state.enrolled = model.touchIDEnrolled }
    }

    private func run(_ work: @escaping () async -> String) {
        state.working = true
        Task {
            state.answer = await work()
            state.enrolled = model.touchIDEnrolled
            state.working = false
        }
    }
}

/// The apps on this Mac where Ira may tap and type without asking. Adding one
/// needs the PIN in a signed-in session, so the list is changed on the web.
struct TrustedAppsRow: View {
    @ObservedObject var approvals: ApprovalMonitor

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("Trusted apps").font(.headline)
                Spacer()
                Button("Change on the Web…") { approvals.openTrustedAppsPage() }
                    .help("Your assistant → Trusted apps in your Ira's web app. Adding an app needs your PIN.")
            }
            Text(approvals.trustedApps.isEmpty
                 ? "None. In a trusted app, Ira acts without asking even outside an approval; the never-list still asks."
                 : approvals.trustedApps.map(ApprovalMonitor.name(of:)).joined(separator: ", "))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .onAppear { Task { await approvals.refresh() } }
    }
}
