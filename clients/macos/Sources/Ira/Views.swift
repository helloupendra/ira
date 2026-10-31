import AppKit
import AVFoundation
import Contacts
import EventKit
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

/// The Keychain did not hand over this Mac's key. Nothing is forgotten: ask
/// again, or pair again.
struct KeyProblemView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Header(title: "Ira can't read its key")
            Text(PairingRecord.unreadable)
                .fixedSize(horizontal: false, vertical: true)
            Text("This happens after installing a new build of Ira: macOS asks whether the new copy may use the key the old one saved. Your pairing is still here.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack {
                Button("Try again") { model.retryKey() }
                    .keyboardShortcut(.defaultAction)
                Button("Pair again") { model.startRepair() }
            }
            Spacer()
        }
        .padding(20)
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

struct PermissionRow: View {
    let permission: Permission
    let ask: () -> Void
    let open: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: permission.icon)
                .font(.title3)
                .foregroundStyle(Color.iraText)
                .frame(width: 26)
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(permission.title).font(.headline)
                    Spacer()
                    switch permission.state {
                    case .granted:
                        Label("Allowed", systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                            .font(.callout)
                    case .missing:
                        // Screen Recording and Accessibility: asking first lists this build of Ira.
                        Button("Open System Settings", action: ["screen", "accessibility"].contains(permission.id) ? ask : open)
                    case .notAsked:
                        if permission.askable { Button("Allow", action: ask) } else { Text("Asked when needed").font(.caption).foregroundStyle(.secondary) }
                    case .unknown:
                        Text("macOS asks the first time").font(.caption).foregroundStyle(.secondary)
                    }
                }
                Text(permission.why)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let note = permission.note, permission.state != .granted {
                    Text(note)
                        .font(.caption)
                        .foregroundStyle(.orange)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if permission.state == .missing && permission.id == "screen" {
                    HStack(alignment: .firstTextBaseline) {
                        Text("Switch Ira on there. macOS then asks to quit and reopen Ira; if it does not, press Reopen Ira.")
                            .font(.caption)
                            .foregroundStyle(.orange)
                            .fixedSize(horizontal: false, vertical: true)
                        Button("Reopen Ira") { PermissionCenter.reopen() }
                            .controlSize(.small)
                    }
                } else if permission.state == .missing && permission.note == nil {
                    Text("Off. Switch Ira on there, then come back.")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            }
        }
    }
}

// MARK: The conversation

struct ChatView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var conversation: Conversation
    @ObservedObject var drop: DropBox
    /// Show another part of the window (a Now card or the Drop pill).
    let openPane: (Pane) -> Void
    @StateObject private var form = FormState()
    @FocusState private var focused: Bool
    @Environment(\.colorScheme) private var scheme

    init(model: AppModel, conversation: Conversation, openPane: @escaping (Pane) -> Void = { _ in }) {
        self.model = model
        self.conversation = conversation
        self.drop = model.drop
        self.openPane = openPane
    }

    var body: some View {
        ZStack {
            Presence.bg.ignoresSafeArea()
            if conversation.entries.isEmpty && !conversation.busy {
                hero
            } else {
                VStack(spacing: 0) {
                    ApprovalBanner(approvals: model.approvals)
                    transcript
                    if conversation.needsRestart {
                        restartBanner
                    }
                    if let notice = conversation.notice {
                        noticeView(notice)
                    }
                    askPill("Reply, or just talk…")
                        .frame(maxWidth: 720)
                        .padding(.horizontal, 24)
                        .padding(.vertical, 16)
                }
            }
            if conversation.listening {
                ListeningView(conversation: conversation, hotKey: hotKeyText)
                    .transition(.opacity)
            }
        }
        .animation(.easeOut(duration: 0.18), value: conversation.listening)
        .navigationTitle(model.assistant)
        .navigationSubtitle(statusText)
        .toolbar {
            if drop.unseen > 0 {
                ToolbarItem {
                    Button("Drop · \(drop.unseen) new") { openPane(.drop) }
                        .buttonStyle(PillButtonStyle())
                        .help("Something new arrived in your Drop")
                }
            }
            ToolbarItem {
                Button("New") {
                    conversation.clear()
                    focused = true
                }
                .buttonStyle(PillButtonStyle())
                .help("New conversation")
                .disabled(conversation.busy)
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .iraFocusInput)) { _ in focused = true }
        .onAppear { focused = true }
    }

    // MARK: An empty conversation

    /// The lens, the greeting, the ask pill and what is worth knowing now.
    private var hero: some View {
        ScrollView {
            VStack(spacing: 22) {
                Spacer(minLength: 36)
                Lens(size: 96, breathing: true, rings: 1)
                VStack(spacing: 8) {
                    greeting
                    Text(dateLine)
                        .font(Presence.secondary)
                        .foregroundStyle(Presence.muted)
                }
                askPill("Ask \(model.assistant) anything, or just start talking…")
                    .frame(maxWidth: 560)
                nowCards
                    .frame(maxWidth: 560)
                Text("\(model.assistant) reads and acts only when you ask. Try “vo PDF kahan hai jo kal download kiya?”")
                    .font(.system(size: 12))
                    .foregroundStyle(Presence.faint)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 460)
                Spacer(minLength: 24)
            }
            .padding(.horizontal, 24)
            .frame(maxWidth: .infinity)
        }
        .background(
            RadialGradient(
                colors: [Color(hex: 0x1F6F5C, opacity: scheme == .dark ? 0.18 : 0.10), .clear],
                center: UnitPoint(x: 0.5, y: 0.28), startRadius: 0, endRadius: 380))
    }

    /// "Good evening, <first name>." with the name from this Mac's account, in italic green.
    private var greeting: Text {
        let hour = Calendar.current.component(.hour, from: Date())
        let part = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening"
        let name = NSFullUserName().split(separator: " ").first.map(String.init) ?? ""
        let words = Text(name.isEmpty ? "\(part)." : "\(part), ").font(Presence.serif(32)).foregroundColor(Presence.ink)
        guard !name.isEmpty else { return words }
        return words + Text(name).font(Presence.serif(32)).italic().foregroundColor(Presence.green)
            + Text(".").font(Presence.serif(32)).foregroundColor(Presence.ink)
    }

    private var dateLine: String {
        let day = Date().formatted(.dateTime.weekday(.wide).day().month(.wide))
        guard model.paired else { return "\(day) · this Mac is not paired yet" }
        if case .connected = model.deviceState { return "\(day) · this Mac is connected" }
        return "\(day) · \(AppDelegate.describe(model.deviceState, paired: true).lowercased())"
    }

    /// Only what is real now: the newest Drop item, and an approval that is open. Never filler.
    @ViewBuilder private var nowCards: some View {
        let latest = drop.items.first
        let approval = model.approvals.banner
        if latest != nil || approval != nil {
            HStack(spacing: 10) {
                if let latest {
                    Button { openPane(.drop) } label: {
                        NowCard(label: "Drop", value: DropList.title(latest), detail: DropList.detail(latest))
                    }
                    .buttonStyle(.plain)
                    .frame(width: 200)
                }
                if let approval {
                    Button { openPane(.thisMac) } label: {
                        NowCard(label: "Approval", value: "Ira may use this Mac", detail: approval)
                    }
                    .buttonStyle(.plain)
                    .frame(width: 200)
                }
            }
        }
    }

    // MARK: The conversation

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
                LazyVStack(alignment: .leading, spacing: 22) {
                    ForEach(conversation.entries) { entry in
                        EntryView(entry: entry, conversation: conversation, server: model.settings.server)
                            .id(entry.id)
                            .transition(.opacity.combined(with: .offset(y: 8)))
                    }
                    if !conversation.caption.isEmpty {
                        Text(conversation.caption)
                            .font(Presence.body)
                            .italic()
                            .foregroundStyle(Presence.muted)
                            .frame(maxWidth: .infinity, alignment: .trailing)
                            .id("caption")
                    }
                    if conversation.busy {
                        ThinkingRow(step: conversation.step, since: conversation.askedAt, stalled: conversation.stalled)
                            .id("thinking")
                    }
                }
                .animation(.easeOut(duration: 0.18), value: conversation.entries.count)
                .padding(.horizontal, 28)
                .padding(.vertical, 24)
                .frame(maxWidth: 760)
                .frame(maxWidth: .infinity)
            }
            .onChange(of: conversation.entries) { _, entries in
                if let last = entries.last { withAnimation { proxy.scrollTo(last.id, anchor: .bottom) } }
            }
            .onChange(of: conversation.busy) { _, busy in
                if busy { withAnimation { proxy.scrollTo("thinking", anchor: .bottom) } }
            }
        }
    }

    private var hotKeyText: String {
        HotKey.describe(keyCode: model.settings.hotKeyCode, modifiers: model.settings.hotKeyModifiers)
    }

    private func noticeView(_ notice: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(notice)
                .font(Presence.secondary)
                .foregroundStyle(Presence.ink)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            HStack {
                if conversation.stalled {
                    Button("Try again") { conversation.tryAgain() }
                        .buttonStyle(PillButtonStyle(filled: true))
                }
                Button("Dismiss") { conversation.notice = nil }
                    .buttonStyle(PillButtonStyle())
            }
        }
        .padding(12)
        .frame(maxWidth: 720, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(Presence.warn.opacity(0.06)))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Presence.warn.opacity(0.45), lineWidth: 1))
        .padding(.horizontal, 24)
    }

    private var restartBanner: some View {
        HStack(alignment: .firstTextBaseline) {
            Text("macOS needs Ira restarted after the Screen Recording permission.")
                .font(Presence.secondary)
                .foregroundStyle(Presence.ink)
                .fixedSize(horizontal: false, vertical: true)
            Spacer()
            Button("Restart Ira") { PermissionCenter.reopen() }
                .buttonStyle(PillButtonStyle(filled: true))
        }
        .padding(12)
        .frame(maxWidth: 720)
        .background(RoundedRectangle(cornerRadius: 12).fill(Presence.warn.opacity(0.06)))
        .padding(.horizontal, 24)
    }

    /// The ask pill: type, or press the mic and talk; the mic turns into Send while there is text.
    private func askPill(_ placeholder: String) -> some View {
        HStack(spacing: 10) {
            TextField(placeholder, text: $form.entry, axis: .vertical)
                .textFieldStyle(.plain)
                .font(Presence.body)
                .foregroundStyle(Presence.ink)
                .lineLimit(1...4)
                .focused($focused)
                .focusEffectDisabled()
                .onSubmit(send)
            if conversation.mode == .speaking {
                Button {
                    conversation.stopSpeaking()
                } label: {
                    Image(systemName: "stop.fill").foregroundStyle(Presence.muted)
                }
                .buttonStyle(.plain)
                .help("Stop speaking")
            }
            KeyHint(text: hotKeyText)
            Button {
                form.entry.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? conversation.toggleListening() : send()
            } label: {
                Image(systemName: form.entry.isEmpty ? "mic" : "arrow.up")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 40, height: 40)
                    .background(Circle().fill(Presence.greenDeep))
            }
            .buttonStyle(.plain)
            .help(form.entry.isEmpty ? "Talk to Ira" : "Send")
            .accessibilityLabel(form.entry.isEmpty ? "Talk to Ira" : "Send")
        }
        .padding(.leading, 20)
        .padding(.trailing, 6)
        .padding(.vertical, 6)
        .background(Capsule().fill(Presence.raised))
        .overlay(Capsule().strokeBorder(Presence.line, lineWidth: 1))
    }

    private func send() {
        let message = form.entry
        form.entry = ""
        conversation.send(message)
    }
}

/// Listening: the large lens with its rings and its bars on the voice, what Ira hears so far,
/// and Cancel and Done. Over the whole conversation while the mic is on.
struct ListeningView: View {
    @ObservedObject var conversation: Conversation
    let hotKey: String
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        ZStack {
            Presence.bg
            RadialGradient(
                colors: [Color(hex: 0x1F6F5C, opacity: scheme == .dark ? 0.22 : 0.12), .clear],
                center: .center, startRadius: 0, endRadius: 440)
            VStack(spacing: 22) {
                Lens(size: 168, level: conversation.level, breathing: true, rings: 2)
                Text(label)
                    .font(Presence.label)
                    .tracking(1.6)
                    .foregroundStyle(Presence.green)
                words
                    .frame(maxWidth: 620)
                HStack(spacing: 12) {
                    Button("Cancel", action: cancel)
                        .buttonStyle(PillButtonStyle())
                        .keyboardShortcut(.cancelAction)
                    Button("Done") { conversation.stopListening() }
                        .buttonStyle(PillButtonStyle(filled: true))
                }
            }
            .padding(24)
            VStack {
                Spacer()
                Text("\(hotKey) brings Ira back · Esc stops listening")
                    .font(.system(size: 12))
                    .foregroundStyle(Presence.faint)
                    .padding(.bottom, 20)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(label)
    }

    private var label: String {
        switch conversation.mode {
        case .hearing: return "HEARING YOU"
        case .thinking: return "THINKING"
        case .speaking: return "SPEAKING"
        default: return "LISTENING"
        }
    }

    @ViewBuilder private var words: some View {
        if !conversation.caption.isEmpty {
            Text("“\(conversation.caption)”")
                .font(Presence.serif(26))
                .foregroundStyle(Presence.ink)
                .multilineTextAlignment(.center)
        } else if [.thinking, .speaking].contains(conversation.mode),
            let answer = conversation.entries.last(where: { $0.role == .ira })?.text, !answer.isEmpty
        {
            Text(answer)
                .font(Presence.body)
                .foregroundStyle(Presence.muted)
                .multilineTextAlignment(.center)
                .lineLimit(5)
        } else {
            Text("Speak now")
                .font(Presence.serif(26))
                .foregroundStyle(Presence.faint)
        }
    }

    private func cancel() {
        conversation.stopSpeaking()
        conversation.stopListening()
    }
}

/// "Ira is working": moving dots in Ira's green, the step in words, and the
/// time since asking after 3 seconds.
struct ThinkingRow: View {
    let step: String
    let since: Date?
    let stalled: Bool

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            HStack(spacing: 12) {
                Lens(size: 30, breathing: !stalled)
                Text(stalled ? "Still waiting…" : step)
                    .font(Presence.body)
                    .foregroundStyle(Presence.muted)
                if let since {
                    let seconds = Int(context.date.timeIntervalSince(since))
                    if seconds >= 3 {
                        Text("\(seconds) s")
                            .font(Presence.mono)
                            .foregroundStyle(Presence.faint)
                    }
                }
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel(stalled ? "Still waiting for an answer" : step)
        }
    }
}

struct EntryView: View {
    let entry: Entry
    @ObservedObject var conversation: Conversation
    let server: String

    private static let yours = UnevenRoundedRectangle(
        topLeadingRadius: 18, bottomLeadingRadius: 18, bottomTrailingRadius: 6, topTrailingRadius: 18)

    var body: some View {
        switch entry.role {
        case .you:
            HStack {
                Spacer(minLength: 80)
                Text(entry.text)
                    .font(Presence.body)
                    .foregroundStyle(Presence.ink)
                    .textSelection(.enabled)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .background(EntryView.yours.fill(Presence.raised))
                    .overlay(EntryView.yours.strokeBorder(Presence.line, lineWidth: 1))
            }
        case .ira:
            HStack(alignment: .top, spacing: 12) {
                Lens(size: 30)
                VStack(alignment: .leading, spacing: 10) {
                    Text(entry.text)
                        .font(Presence.body)
                        .lineSpacing(5)
                        .foregroundStyle(Presence.ink)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if !entry.receipts.isEmpty {
                        HStack(spacing: 6) {
                            ForEach(entry.receipts, id: \.self) { ReceiptChip(text: $0) }
                        }
                        .accessibilityElement(children: .combine)
                        .accessibilityLabel("How Ira got this: " + entry.receipts.joined(separator: ", "))
                    }
                }
                .padding(.top, 4)
            }
        case .note:
            if let action = entry.action {
                ActionCard(action: action, conversation: conversation, server: server)
                    .padding(.leading, 42)
            } else {
                Text(entry.text)
                    .font(Presence.secondary)
                    .foregroundStyle(Presence.muted)
                    .padding(.leading, 42)
            }
        }
    }
}

final class PinState: ObservableObject {
    @Published var pin = ""
    @Published var working = false
    @Published var answer: String?
}

struct ActionCard: View {
    let action: PendingAction
    @ObservedObject var conversation: Conversation
    let server: String
    @StateObject private var state = PinState()

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if action.status == "pending" {
                DotLabel(text: "Waiting for you", color: Presence.warn)
            } else {
                DotLabel(text: ActionCard.outcome(action.status), color: action.status == "executed" ? Presence.green : Presence.muted)
            }
            Text(action.summary)
                .font(Presence.body)
                .foregroundStyle(Presence.ink)
                .fixedSize(horizontal: false, vertical: true)
            if action.status == "pending" {
                if action.tier == 2 {
                    HStack {
                        Spacer()
                        Button("Not now") { conversation.answer(action, yes: false) }
                            .buttonStyle(PillButtonStyle())
                        Button("Yes") { conversation.answer(action, yes: true) }
                            .buttonStyle(PillButtonStyle(filled: true))
                            .keyboardShortcut(.defaultAction)
                    }
                } else {
                    HStack(spacing: 10) {
                        SecureField("PIN", text: $state.pin)
                            .textFieldStyle(.plain)
                            .font(.system(size: 15, design: .monospaced))
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                            .frame(width: 130)
                            .background(RoundedRectangle(cornerRadius: 8).fill(Presence.card))
                            .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Presence.line, lineWidth: 1))
                            .onSubmit(confirm)
                        if conversation.touchIDReady(for: action) {
                            Button {
                                touchID()
                            } label: {
                                Label("Touch ID", systemImage: "touchid")
                            }
                            .buttonStyle(PillButtonStyle())
                            .disabled(state.working)
                            .help("Approve with your fingerprint instead of the PIN.")
                        }
                        Spacer()
                        Button("Not now") { conversation.answer(action, yes: false) }
                            .buttonStyle(PillButtonStyle())
                        Button(state.working ? "Checking…" : "Confirm", action: confirm)
                            .buttonStyle(PillButtonStyle(filled: true))
                            .disabled(state.working || state.pin.count < 4)
                    }
                    Text("Typed here, your PIN goes only to your Ira's confirm step, never to the assistant. Never say it aloud.")
                        .font(.system(size: 12))
                        .foregroundStyle(Presence.faint)
                }
                if let answer = state.answer {
                    Text(answer).font(Presence.secondary).foregroundStyle(Presence.ink)
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 14).fill(action.status == "pending" ? Presence.warn.opacity(0.06) : Presence.card))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(
            action.status == "pending" ? Presence.warn.opacity(0.55) : Presence.line, lineWidth: 1))
    }

    static func outcome(_ status: String) -> String {
        switch status {
        case "yes": return "You said yes."
        case "no": return "You said no."
        case "executed": return "Done."
        case "failed": return "It ran but failed."
        case "expired": return "It expired before an answer."
        case "cancelled": return "Cancelled."
        default: return status
        }
    }

    private func touchID() {
        state.working = true
        Task {
            state.answer = await conversation.confirmWithTouchID(action)
            state.working = false
        }
    }

    private func confirm() {
        let pin = state.pin
        state.pin = ""
        state.working = true
        Task {
            state.answer = await conversation.confirm(action, pin: pin)
            state.working = false
        }
    }
}

/// While an approval window is open: how long Ira may still control this Mac
/// without asking, and Stop.
struct ApprovalBanner: View {
    @ObservedObject var approvals: ApprovalMonitor

    var body: some View {
        if let banner = approvals.banner {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Image(systemName: "hand.point.up.left.fill")
                        .foregroundStyle(.orange)
                    Text(banner)
                        .font(.callout.weight(.medium))
                    if let steps = approvals.window?.steps, steps > 0 {
                        Text("· \(steps) step\(steps == 1 ? "" : "s")")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("Stop") { Task { await approvals.stop() } }
                        .controlSize(.small)
                        .help("End it now: the next step asks for your PIN again.")
                }
                if !approvals.trustedApps.isEmpty {
                    Text("Trusted apps: " + approvals.trustedApps.map(ApprovalMonitor.name(of:)).joined(separator: ", "))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let problem = approvals.problem {
                    Text(problem).font(.caption).foregroundStyle(.orange)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Color.orange.opacity(0.12))
        }
    }
}
