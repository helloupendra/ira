import AppKit
import AVFoundation
import IraKit
import SwiftUI

extension Color {
    /// The repository's green, for fills under white.
    static let ira = Color(red: 0x1f / 255, green: 0x6f / 255, blue: 0x5c / 255)
    /// The same green for text and icons: lighter in dark mode, so it stays readable.
    static let iraText = Color(nsColor: NSColor(name: nil) { appearance in
        appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            ? NSColor(red: 0.42, green: 0.78, blue: 0.67, alpha: 1)
            : NSColor(red: 0x1f / 255, green: 0x6f / 255, blue: 0x5c / 255, alpha: 1)
    })
}

struct MainView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var conversation: Conversation
    let openSettings: () -> Void

    var body: some View {
        Group {
            switch model.screen {
            case .pair: PairView(model: model)
            case .permissions: PermissionsView(model: model)
            case .chat: ChatView(model: model, conversation: conversation, openSettings: openSettings)
            }
        }
        .frame(minWidth: 340, minHeight: 420)
    }
}

// MARK: Pairing

/// A form's own state. SwiftUI's @State is a compiler macro in the newest SDKs,
/// whose plugin ships with Xcode only; small observable objects build everywhere.
final class FormState: ObservableObject {
    @Published var entry = ""
    @Published var server = ""
    @Published var email = ""
    @Published var password = ""
    @Published var working = false
    @Published var problem: String?
    @Published var flag = false
}

struct PairView: View {
    @ObservedObject var model: AppModel
    @StateObject private var form = FormState()

    private var needsServer: Bool {
        let text = form.entry.trimmingCharacters(in: .whitespaces)
        return !text.isEmpty && !text.contains("://")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Header(title: "Pair this Mac with your Ira")
            Text("On your Ira's **Your devices** page, add a Mac, choose what it may do, and make a pairing code. Then paste the pairing link here, or type the code.")
                .fixedSize(horizontal: false, vertical: true)
            TextField("Pairing link or code (ABCD-EFGH)", text: $form.entry)
                .textFieldStyle(.roundedBorder)
                .onSubmit(pair)
            if needsServer {
                TextField("Your Ira's address, e.g. https://ira.example.com", text: $form.server)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit(pair)
            }
            HStack {
                Button(action: pair) {
                    Text(form.working ? "Pairing…" : "Pair")
                        .frame(minWidth: 80)
                }
                .keyboardShortcut(.defaultAction)
                .disabled(form.working || form.entry.trimmingCharacters(in: .whitespaces).isEmpty)
                Button("Paste") { pasteFromClipboard() }
                    .disabled(form.working)
            }
            if let problem = form.problem {
                Label(problem, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
            Text("The code works once, for 10 minutes. This Mac gets its own key, kept in your Keychain; removing the Mac on Your devices stops it at once.")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(20)
        .onAppear(perform: pasteIfLink)
    }

    private func pasteIfLink() {
        if form.entry.isEmpty, let text = NSPasteboard.general.string(forType: .string), text.contains("/pair#code=") {
            form.entry = String(text.trimmingCharacters(in: .whitespacesAndNewlines).prefix(300))
        }
    }

    private func pasteFromClipboard() {
        if let text = NSPasteboard.general.string(forType: .string) {
            form.entry = String(text.trimmingCharacters(in: .whitespacesAndNewlines).prefix(300))
        }
    }

    private func pair() {
        form.problem = nil
        form.working = true
        Task {
            do {
                try await model.pair(entry: form.entry, server: form.server)
            } catch {
                form.problem = "Not paired: \(error.localizedDescription)"
            }
            form.working = false
        }
    }
}

struct Header: View {
    let title: String
    var body: some View {
        HStack(spacing: 10) {
            Image(nsImage: NSApp.applicationIconImage)
                .resizable()
                .frame(width: 28, height: 28)
            Text(title).font(.title3.weight(.semibold))
        }
        .padding(.top, 8)
    }
}

// MARK: First run

final class PermissionState: ObservableObject {
    @Published var mic = AudioIO.micPermission
    @Published var screen = ScreenText.permitted
}

struct PermissionsView: View {
    @ObservedObject var model: AppModel
    @StateObject private var state = PermissionState()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Header(title: "What Ira may use on this Mac")
                Text("Ira reads nothing until you ask. macOS asks you before Ira uses each of these; you can change your mind in System Settings → Privacy & Security at any time.")
                    .fixedSize(horizontal: false, vertical: true)
                PermissionRow(
                    icon: "mic", title: "Microphone",
                    text: "So you can talk to Ira. It listens only after you press the mic button, and stops when you press it again or stay quiet.",
                    granted: state.mic == .authorized,
                    actionTitle: state.mic == .notDetermined ? "Allow" : "Open Settings",
                    action: askMic)
                PermissionRow(
                    icon: "folder", title: "Files and folders",
                    text: "So Ira can find a file and read it to you. macOS asks the first time Ira opens something in Documents, Desktop or Downloads; say Allow. Ira never reads your Library folder, keychains or hidden files.",
                    granted: false, actionTitle: nil, action: {})
                PermissionRow(
                    icon: "macwindow", title: "Screen Recording",
                    text: "Only for “what is on my screen?”. Ira takes a picture of the window in front, reads its text on this Mac, and sends only the text. Turn on the Screen skill for this Mac in Ira too.",
                    granted: state.screen,
                    actionTitle: "Allow",
                    action: askScreen)
                Text("On your Ira's **Your devices** page, switch on the skills you want this Mac to have, such as Files and Screen. Each needs your PIN.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                HStack {
                    Spacer()
                    Button("Done") { model.finishFirstRun() }
                        .keyboardShortcut(.defaultAction)
                }
            }
            .padding(20)
        }
    }

    private func askMic() {
        if state.mic == .notDetermined {
            Task {
                _ = await AudioIO.askMicPermission()
                state.mic = AudioIO.micPermission
            }
        } else {
            openPrivacy("Privacy_Microphone")
        }
    }

    private func askScreen() {
        ScreenText.requestPermission()
        state.screen = ScreenText.permitted
        if !state.screen { openPrivacy("Privacy_ScreenCapture") }
    }
}

func openPrivacy(_ anchor: String) {
    if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(anchor)") {
        NSWorkspace.shared.open(url)
    }
}

struct PermissionRow: View {
    let icon: String
    let title: String
    let text: String
    let granted: Bool
    let actionTitle: String?
    let action: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.title2)
                .foregroundStyle(Color.iraText)
                .frame(width: 28)
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(title).font(.headline)
                    Spacer()
                    if granted {
                        Label("Allowed", systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                            .font(.callout)
                    } else if let actionTitle {
                        Button(actionTitle, action: action)
                    }
                }
                Text(text)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

// MARK: The conversation

struct ChatView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var conversation: Conversation
    let openSettings: () -> Void
    @StateObject private var form = FormState()
    @FocusState private var focused: Bool

    var body: some View {
        VStack(spacing: 0) {
            topBar
            Divider()
            transcript
            if let notice = conversation.notice {
                noticeView(notice)
            }
            if form.flag { activityList }
            Divider()
            composer
        }
        .onReceive(NotificationCenter.default.publisher(for: .iraFocusInput)) { _ in focused = true }
    }

    private var topBar: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(statusColor)
                .frame(width: 8, height: 8)
            Text(model.assistant).font(.headline)
            Text(statusText)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
            Spacer()
            Button {
                form.flag.toggle()
            } label: {
                Image(systemName: "list.bullet.rectangle")
            }
            .buttonStyle(.borderless)
            .help("What I read")
            Menu {
                Button("New conversation") { conversation.clear() }
                Button("Settings…", action: openSettings)
            } label: {
                Image(systemName: "ellipsis.circle")
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()
        }
        .padding(.horizontal, 14)
        .padding(.top, 30)
        .padding(.bottom, 8)
    }

    private var statusColor: Color {
        switch model.deviceState {
        case .connected: return .green
        case .connecting, .waiting: return .orange
        case .refused, .stopped: return .red
        }
    }

    private var statusText: String {
        switch conversation.mode {
        case .listening: return "Listening"
        case .hearing: return "Hearing you"
        case .thinking: return "Thinking"
        case .speaking: return "Speaking"
        case .idle: return AppDelegate.describe(model.deviceState, paired: model.paired)
        }
    }

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    if conversation.entries.isEmpty {
                        Text("Ask by typing or press the mic and talk. Try “vo PDF kahan hai jo kal download kiya?” or “screen pe kya hai?”.")
                            .foregroundStyle(.secondary)
                            .padding(.top, 20)
                    }
                    ForEach(conversation.entries) { entry in
                        EntryView(entry: entry, conversation: conversation, server: model.settings.server)
                            .id(entry.id)
                    }
                    if !conversation.caption.isEmpty {
                        Text(conversation.caption)
                            .italic()
                            .foregroundStyle(.secondary)
                            .id("caption")
                    }
                }
                .padding(14)
            }
            .onChange(of: conversation.entries) { _, entries in
                if let last = entries.last { withAnimation { proxy.scrollTo(last.id, anchor: .bottom) } }
            }
        }
    }

    private func noticeView(_ notice: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(notice)
                .font(.callout)
                .fixedSize(horizontal: false, vertical: true)
            if conversation.needsSignIn {
                SignInForm(model: model)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.orange.opacity(0.12))
    }

    private var activityList: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("What I read").font(.caption.weight(.semibold))
            if model.activity.isEmpty {
                Text("Nothing yet. Ira reads only when you ask.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            ForEach(model.activity.prefix(8)) { entry in
                HStack(alignment: .firstTextBaseline) {
                    Image(systemName: entry.ok ? "checkmark" : "xmark")
                        .foregroundStyle(entry.ok ? Color.secondary : Color.red)
                        .font(.caption2)
                    Text("\(entry.verb): \(entry.target)")
                        .font(.caption)
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Spacer()
                    Text(entry.at, style: .time)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(10)
        .background(Color.secondary.opacity(0.08))
    }

    private var composer: some View {
        HStack(spacing: 10) {
            TextField("Ask \(model.assistant)…", text: $form.entry, axis: .vertical)
                .textFieldStyle(.plain)
                .lineLimit(1...4)
                .focused($focused)
                .onSubmit(send)
            if conversation.mode == .speaking {
                Button {
                    conversation.stopSpeaking()
                } label: {
                    Image(systemName: "stop.fill")
                }
                .buttonStyle(.borderless)
                .help("Stop speaking")
            }
            MicButton(listening: conversation.listening, level: conversation.level) {
                conversation.toggleListening()
            }
        }
        .padding(12)
    }

    private func send() {
        let message = form.entry
        form.entry = ""
        conversation.send(message)
    }
}

struct MicButton: View {
    let listening: Bool
    let level: Float
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                Circle()
                    .stroke(Color.ira.opacity(listening ? 0.35 : 0), lineWidth: 6)
                    .scaleEffect(1 + CGFloat(min(level * 8, 0.35)))
                Circle()
                    .fill(listening ? Color.red : Color.ira)
                Image(systemName: listening ? "mic.fill" : "mic")
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(.white)
            }
            .frame(width: 48, height: 48)
        }
        .buttonStyle(.plain)
        .help(listening ? "Stop listening" : "Talk to Ira")
        .accessibilityLabel(listening ? "Stop listening" : "Talk to Ira")
    }
}

struct EntryView: View {
    let entry: Entry
    @ObservedObject var conversation: Conversation
    let server: String

    var body: some View {
        switch entry.role {
        case .you:
            HStack {
                Spacer(minLength: 40)
                Text(entry.text)
                    .textSelection(.enabled)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 7)
                    .background(Color.ira.opacity(0.14), in: RoundedRectangle(cornerRadius: 10))
            }
        case .ira:
            Text(entry.text)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        case .note:
            if let action = entry.action {
                ActionCard(action: action, conversation: conversation, server: server)
            } else {
                Text(entry.text).font(.callout).foregroundStyle(.secondary)
            }
        }
    }
}

struct ActionCard: View {
    let action: PendingAction
    @ObservedObject var conversation: Conversation
    let server: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(action.tier == 2 ? "Needs your yes" : "Needs your PIN")
                .font(.caption.weight(.semibold))
                .foregroundStyle(Color.iraText)
            Text(action.summary)
            if action.status == "pending" {
                if action.tier == 2 {
                    HStack {
                        Button("Yes") { conversation.answer(action, yes: true) }
                            .keyboardShortcut(.defaultAction)
                        Button("No") { conversation.answer(action, yes: false) }
                    }
                } else {
                    Text("Confirm it with your PIN in the Ira app. A PIN is never spoken or typed here.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Button("Open Ira") {
                        if let url = URL(string: server) { NSWorkspace.shared.open(url) }
                    }
                }
            } else {
                Text(action.status == "yes" ? "You said yes." : action.status == "no" ? "You said no." : action.status)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).stroke(Color.ira.opacity(0.4)))
    }
}

struct SignInForm: View {
    @ObservedObject var model: AppModel
    @StateObject private var form = FormState()

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            TextField("Email", text: $form.email)
                .textFieldStyle(.roundedBorder)
                .textContentType(.username)
            SecureField("Password", text: $form.password)
                .textFieldStyle(.roundedBorder)
                .textContentType(.password)
                .onSubmit(signIn)
            HStack {
                Button(form.working ? "Signing in…" : "Sign in", action: signIn)
                    .disabled(form.working || form.email.isEmpty || form.password.isEmpty)
                if let problem = form.problem {
                    Text(problem).font(.caption).foregroundStyle(.red)
                }
            }
        }
    }

    private func signIn() {
        form.working = true
        form.problem = nil
        Task {
            do {
                try await model.signIn(email: form.email, password: form.password)
                form.password = ""
            } catch {
                form.problem = error.localizedDescription
            }
            form.working = false
        }
    }
}
