import AppKit
import Foundation
import IraKit

/// One line in the window: what the person said, what Ira answered, or a note.
struct Entry: Identifiable, Equatable {
    enum Role { case you, ira, note }
    let id = UUID()
    let role: Role
    var text: String
    var turn: Int?
    var action: PendingAction?
}

struct PendingAction: Equatable {
    let id: String
    let summary: String
    let tier: Int
    var status: String
}

/// The conversation in the window: typing, the live microphone, and Ira's voice.
///
/// It picks the transport: live voice when the server has it, else the HTTP API;
/// both sign in with this Mac's device token. One conversation id per window
/// (kept for 30 minutes), so the conversation goes on across reconnects and
/// shows in the person's web chat too.
@MainActor
final class Conversation: ObservableObject {
    enum Mode: Equatable { case idle, listening, hearing, thinking, speaking }

    @Published var entries: [Entry] = []
    @Published var caption = ""
    @Published var mode: Mode = .idle
    @Published var listening = false
    @Published var level: Float = 0
    @Published var notice: String?
    @Published var transportKind: String?
    /// What this Mac's key may do for its person (from /v1/info): ask, voice, actions.
    @Published var permissions: [String] = []
    /// A question is on its way: from asking until the answer is complete.
    @Published var busy = false
    /// What Ira is doing for it now: "Thinking…", "Reading the screen…".
    @Published var step = "Thinking…"
    /// When the question was asked, for the elapsed time.
    @Published var askedAt: Date?
    /// Nothing heard back for 30 seconds.
    @Published var stalled = false
    /// macOS needs Ira restarted before the screen can be read.
    @Published var needsRestart = false
    /// The answer, complete: for a notification while the window is hidden.
    var onAnswer: ((String) -> Void)?
    private var lastQuestion: String?
    private var lastProgress = Date()
    private var watchdog: Timer?

    private let settings: AppSettings
    private let secrets: SecretStore
    private let audio = AudioIO()
    private var vad = EnergyVAD()
    private var transport: VoiceTransport?
    private var connecting: Task<VoiceTransport?, Never>?
    /// Why live voice last failed to start, while the HTTP API carries the
    /// conversation; live is tried again on the next mic press, and when the
    /// device connection comes back.
    private(set) var liveProblem: String?
    private var lastInputWasVoice = false
    /// A typed turn waiting for its turn number, so a "heard" for it is not shown twice.
    private var typed: (id: UUID, text: String)?
    private var interruptedTurn = 0
    private var lastActivity = Date()
    private var idleTimer: Timer?
    /// Called when listening stops, so "Hey Ira" can listen again.
    var onListeningEnded: (() -> Void)?
    /// This window's conversation.
    private(set) var conversationID: String

    init(settings: AppSettings, secrets: SecretStore) {
        self.settings = settings
        self.secrets = secrets
        conversationID = settings.recentConversation() ?? Conversation.newID()
        audio.onFrame = { [weak self] samples, at in self?.frame(samples, at: at) }
        audio.onTurnStarted = { [weak self] turn in
            guard let self else { return }
            self.mode = .speaking
            self.transport?.played(turn: turn, at: monotonicMs())
        }
        audio.onIdle = { [weak self] in
            guard let self else { return }
            self.vad.replying = false
            if self.mode == .speaking { self.mode = self.listening ? .listening : .idle }
            self.lastActivity = Date()
        }
    }

    var server: String { settings.server }

    static func newID() -> String {
        "mac-" + UUID().uuidString.lowercased().replacingOccurrences(of: "-", with: "").prefix(12)
    }

    // MARK: Connecting

    func connect() async -> VoiceTransport? {
        if let transport { return transport }
        if let connecting { return await connecting.value }
        let task = Task<VoiceTransport?, Never> { await self.open() }
        connecting = task
        let result = await task.value
        connecting = nil
        return result
    }

    private func open() async -> VoiceTransport? {
        let events: @Sendable (TalkEvent) -> Void = { [weak self] event in
            Task { @MainActor in self?.handle(event) }
        }
        guard let token = secrets.load(SecretAccount.device), !settings.server.isEmpty else {
            notice = "This Mac is not paired with your Ira yet. Pair it first (Settings → Pair again)."
            return nil
        }
        let client = AskClient(server: settings.server, token: { token })
        if let info = try? await client.info() {
            permissions = (info["permissions"]?.arrayValue ?? []).compactMap(\.stringValue)
            if !permissions.contains("ask") {
                notice = "Your Ira account may not talk to Ira (a viewer account). Ask the person who runs your Ira to change your role."
                return nil
            }
        }
        do {
            let live = try LiveVoiceTransport(server: settings.server, token: token)
            try await live.start(conversationID: conversationID, events: events)
            if liveProblem != nil { IraLog.shared.info("live voice is back") }
            liveProblem = nil
            return use(live)
        } catch {
            liveProblem = error.localizedDescription
            IraLog.shared.info("live voice unavailable, using the HTTP API: \(error.localizedDescription)")
        }
        let http = HTTPVoiceTransport(client: client, speakReplies: { [settings] in settings.speakReplies })
        do {
            try await http.start(conversationID: conversationID, events: events)
            return use(http)
        } catch let failure as AskClient.Failure {
            notice = failure.signedOut
                ? "Your Ira no longer knows this Mac (it was removed on Your devices). Pair it again in Settings."
                : "Ira cannot be reached right now: \(failure.message). Check your internet connection, then try again."
            return nil
        } catch {
            notice = "Ira cannot be reached right now. Check your internet connection, then try again."
            return nil
        }
    }

    private func use(_ transport: VoiceTransport) -> VoiceTransport {
        self.transport = transport
        transportKind = transport.kind
        notice = nil
        return transport
    }

    /// Leave the HTTP fallback, so the next turn tries live voice first again.
    /// Only between turns: nothing under way is cut off.
    func retryLive(_ why: String) {
        guard liveProblem != nil, transport?.kind == "http", connecting == nil, !busy, !listening else { return }
        IraLog.shared.info("trying live voice again (\(why))")
        transport?.close()
        transport = nil
        transportKind = nil
    }

    /// Close the connection (the window closed, or the person signed out).
    func disconnect() {
        stopListening()
        audio.stopPlayback()
        transport?.close()
        transport = nil
        transportKind = nil
    }

    // MARK: Showing that Ira is working

    private func began(_ step: String) {
        busy = true
        stalled = false
        self.step = step
        askedAt = Date()
        lastProgress = Date()
        watchdog?.invalidate()
        watchdog = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self, self.busy else { return }
                if Date().timeIntervalSince(self.lastProgress) > 30, !self.stalled {
                    self.stalled = true
                    self.notice = "No answer yet. The server is slow or unreachable."
                }
                self.objectWillChange.send()  // the elapsed time
            }
        }
    }

    private func progressed(_ step: String? = nil) {
        lastProgress = Date()
        if stalled {
            stalled = false
            notice = nil
        }
        if let step { self.step = step }
    }

    private func finished() {
        busy = false
        stalled = false
        askedAt = nil
        watchdog?.invalidate()
        watchdog = nil
    }

    /// Ask the last question again (after "No answer yet").
    func tryAgain() {
        guard let question = lastQuestion else { return }
        transport?.interrupt()
        disconnect()
        notice = nil
        finished()
        send(question)
    }

    // MARK: Typing

    func send(_ text: String) {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        lastInputWasVoice = false
        lastQuestion = text
        let entry = Entry(role: .you, text: text)
        typed = (entry.id, text)
        entries.append(entry)
        mode = .thinking
        notice = nil
        began(transport == nil ? "Connecting to your Ira…" : "Thinking…")
        Task {
            guard let transport = await connect() else {
                mode = .idle
                finished()
                if notice == nil {
                    notice = "Ira could not be reached. Check that this Mac is online and paired, then try again."
                }
                return
            }
            progressed("Thinking…")
            stopSpeaking()
            transport.text(text)
        }
    }

    /// Answer a Tier 2 proposal: a yes or no in the same conversation.
    func answer(_ action: PendingAction, yes: Bool) {
        if let index = entries.firstIndex(where: { $0.action?.id == action.id }) {
            entries[index].action?.status = yes ? "yes" : "no"
        }
        send(yes ? "yes" : "no")
    }

    // MARK: Listening

    func toggleListening() {
        listening ? stopListening() : startListening()
    }

    func startListening() {
        Task {
            switch AudioIO.micPermission {
            case .authorized: break
            case .notDetermined:
                guard await AudioIO.askMicPermission() else {
                    notice = "Ira cannot hear you: the microphone is off for Ira in System Settings → Privacy & Security → Microphone."
                    return
                }
            default:
                notice = "Ira cannot hear you: allow Ira in System Settings → Privacy & Security → Microphone."
                return
            }
            retryLive("the mic was pressed")
            guard await connect() != nil else { return }
            do {
                try audio.startListening()
            } catch {
                notice = "The microphone did not start: \(error.localizedDescription)"
                return
            }
            vad = EnergyVAD()
            listening = true
            mode = .listening
            notice = nil
            lastActivity = Date()
            startIdleTimer()
        }
    }

    func stopListening() {
        guard listening else { return }
        if vad.speaking { transport?.speechEnd(at: monotonicMs()) }
        audio.stopListening()
        vad.reset()
        listening = false
        level = 0
        caption = ""
        idleTimer?.invalidate()
        if mode == .listening || mode == .hearing { mode = .idle }
        onListeningEnded?()
    }

    /// Stop Ira talking (the stop button, or the person started to speak).
    func stopSpeaking() {
        guard audio.playing else { return }
        audio.stopPlayback()
        vad.replying = false
        interruptedTurn = max(interruptedTurn, entries.compactMap(\.turn).max() ?? 0)
        if mode == .speaking { mode = listening ? .listening : .idle }
    }

    private func startIdleTimer() {
        idleTimer?.invalidate()
        idleTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.listening else { return }
                // Nobody spoke for a while and Ira is quiet: stop listening.
                if Date().timeIntervalSince(self.lastActivity) > 45, self.mode == .listening {
                    self.stopListening()
                    self.notice = "Stopped listening. Press the mic to talk again."
                }
            }
        }
    }

    private func frame(_ samples: [Float], at: Double) {
        vad.replying = audio.playing
        for output in vad.process(samples, at: at) {
            switch output {
            case .speechStart(let start):
                if audio.playing {
                    // Barge-in: stop at once, without waiting for the server.
                    stopSpeaking()
                }
                lastInputWasVoice = true
                mode = .hearing
                lastActivity = Date()
                transport?.speechStart(at: start)
            case .audio(let pcm):
                transport?.audio(pcm)
            case .speechEnd(let end):
                transport?.speechEnd(at: end)
                mode = .thinking
                lastActivity = Date()
                began("Listening done. Thinking…")
            }
        }
        level = vad.level
    }

    // MARK: Ira's answers

    private func entryIndex(turn: Int) -> Int? {
        entries.lastIndex(where: { $0.role == .ira && $0.turn == turn })
    }

    private func handle(_ event: TalkEvent) {
        switch event {
        case .ready(let conversationID, let assistant):
            if let conversationID {
                self.conversationID = conversationID
                settings.rememberConversation(conversationID)
            }
            if let assistant, !assistant.isEmpty { settings.assistantName = assistant }
        case .partial(let text):
            caption = text
        case .heard(let turn, let text):
            caption = ""
            if !busy { began("Thinking…") }
            progressed("Thinking…")
            if lastInputWasVoice { lastQuestion = text }
            if let typed, typed.text == text, let index = entries.firstIndex(where: { $0.id == typed.id }) {
                entries[index].turn = turn
            } else {
                entries.append(Entry(role: .you, text: text, turn: turn))
            }
            typed = nil
            mode = .thinking
        case .tool(_, let name):
            progressed(Conversation.phrase(name))
        case .delta(let turn, let text):
            caption = ""
            progressed()
            if let index = entryIndex(turn: turn) {
                entries[index].text += text
            } else {
                entries.append(Entry(role: .ira, text: text, turn: turn))
            }
            if mode == .thinking { mode = listening ? .listening : .idle }
        case .audio(let turn, _, _, let data):
            guard turn > interruptedTurn, lastInputWasVoice || settings.speakReplies else { return }
            vad.replying = true
            audio.play(mp3: data, turn: turn)
        case .say(let turn, _, let text):
            guard turn > interruptedTurn, lastInputWasVoice || settings.speakReplies else { return }
            vad.replying = true
            audio.say(text, turn: turn)
        case .action(let turn, let action):
            let pending = PendingAction(
                id: action["id"]?.stringValue ?? "",
                summary: action["summary"]?.stringValue ?? "Ira proposed an action",
                tier: action["tier"]?.intValue ?? 3,
                status: action["status"]?.stringValue ?? "pending")
            entries.append(Entry(role: .note, text: pending.summary, turn: turn, action: pending))
        case .done(let turn, let text):
            if let index = entryIndex(turn: turn) {
                if !text.isEmpty { entries[index].text = text }
            } else if !text.isEmpty {
                entries.append(Entry(role: .ira, text: text, turn: turn))
            }
            finished()
            let answer = text.isEmpty ? (entryIndex(turn: turn).map { entries[$0].text } ?? "") : text
            onAnswer?(answer)
            caption = ""
            if mode == .thinking { mode = listening ? .listening : .idle }
            lastActivity = Date()
        case .interrupted(let turn):
            interruptedTurn = max(interruptedTurn, turn)
            finished()
        case .error(let message, let fatal):
            notice = Conversation.plain(message)
            finished()
            if mode == .thinking { mode = listening ? .listening : .idle }
            if fatal { disconnect() }
        case .closed(let reason):
            transport = nil
            transportKind = nil
            if busy {
                finished()
                notice = "The connection to your Ira dropped before the answer came. Press Try again."
                stalled = true
            }
            if listening {
                stopListening()
                notice = "The connection to Ira dropped\(reason.map { " (\($0))" } ?? ""). Press the mic to talk again."
            }
        }
    }

    /// A server's error, as a sentence with what to do next.
    static func plain(_ message: String) -> String {
        let text = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return "Something went wrong on your Ira. Try again." }
        let sentence = text.prefix(1).uppercased() + text.dropFirst()
        if sentence.hasSuffix(".") || sentence.hasSuffix("?") || sentence.hasSuffix("!") { return sentence }
        return sentence + ". Try again, or ask it another way."
    }

    static func phrase(_ tool: String) -> String {
        switch tool {
        case "files_find": return "Finding files…"
        case "file_read": return "Reading the file…"
        case "file_open": return "Opening it…"
        case "screen_read": return "Reading the screen…"
        case "browser_tabs": return "Looking at your browser tabs…"
        case "browser_show_tab": return "Switching to the tab…"
        case "contacts_lookup": return "Looking in your contacts…"
        case "calendar_read", "calendar_add": return "Checking your calendar…"
        case "reminders_list", "reminders_add", "reminders_done": return "Checking your reminders…"
        case "mail_search", "mail_read", "mail_draft": return "Checking your mail…"
        case "messages_send": return "Sending the message…"
        case "notes_search", "notes_read", "notes_add": return "Checking your notes…"
        case "app_open", "url_open", "vscode_open": return "Opening it…"
        case "clipboard_read": return "Reading the clipboard…"
        case "shortcuts_list", "shortcuts_run": return "Running the shortcut…"
        case "code_task_start", "code_task_status", "code_task_list", "code_task_stop", "code_task_push": return "Working on the task…"
        default: return "Working…"
        }
    }

    func clear() {
        entries.removeAll()
        conversationID = Conversation.newID()
        settings.rememberConversation(conversationID)
        disconnect()
    }

    /// Confirm a Tier 3 action with the PIN typed here; the PIN goes only to the
    /// confirm endpoint, never to a model. Returns a sentence for the card.
    func confirm(_ action: PendingAction, pin: String) async -> String {
        guard let token = secrets.load(SecretAccount.device) else { return "This Mac is not paired." }
        let client = AskClient(server: settings.server, token: { token })
        let outcome: JSONValue
        do {
            outcome = try await client.confirm(actionID: action.id, pin: pin)
        } catch {
            return "Ira could not be reached: \(error.localizedDescription). Try again."
        }
        let status = outcome["status"]?.stringValue ?? ""
        if let index = entries.firstIndex(where: { $0.action?.id == action.id }), status != "wrong_pin" {
            entries[index].action?.status = status
        }
        switch status {
        case "executed": return "Done."
        case "wrong_pin":
            let left = outcome["attempts_left"]?.intValue.map { " \($0) tries left." } ?? ""
            return "That PIN is not right.\(left)"
        case "locked": return "Too many wrong PINs: actions are locked for a while. Try again later."
        case "expired": return "This proposal expired. Ask Ira again."
        case "no_pin": return "You have no PIN yet. Set one in the Ira app's menu, then ask again."
        case "not_allowed": return "Your role may not confirm this action."
        case "failed": return "It ran but failed: \(outcome["message"]?.stringValue ?? "no reason given")."
        default: return outcome["message"]?.stringValue ?? "Ira answered: \(status)."
        }
    }
}
