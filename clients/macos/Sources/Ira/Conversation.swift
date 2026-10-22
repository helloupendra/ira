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
/// It picks the transport: live voice with this Mac's device token when the
/// server has it, else the HTTP API with a signed-in session.
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
    @Published var needsSignIn = false

    private let settings: AppSettings
    private let secrets: SecretStore
    private let audio = AudioIO()
    private var vad = EnergyVAD()
    private var transport: VoiceTransport?
    private var connecting: Task<VoiceTransport?, Never>?
    private var lastInputWasVoice = false
    /// A typed turn waiting for its turn number, so a "heard" for it is not shown twice.
    private var typed: (id: UUID, text: String)?
    private var interruptedTurn = 0
    private var lastActivity = Date()
    private var idleTimer: Timer?
    /// "Hey Ira" comes later: a detector plugged in here would start listening.
    var wakeWord: WakeWordDetector?

    init(settings: AppSettings, secrets: SecretStore) {
        self.settings = settings
        self.secrets = secrets
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
        var liveProblem: String?
        if let token = secrets.load(SecretAccount.device), !settings.server.isEmpty {
            do {
                let live = try LiveVoiceTransport(server: settings.server, token: token)
                try await live.start(conversationID: settings.recentConversation(), events: events)
                return use(live)
            } catch {
                liveProblem = error.localizedDescription
                IraLog.shared.info("live voice unavailable: \(liveProblem ?? "")")
            }
        }
        if let session = secrets.load(SecretAccount.session) {
            let client = AskClient(server: settings.server, token: { session })
            let http = HTTPVoiceTransport(client: client, speakReplies: { [settings] in settings.speakReplies })
            do {
                try await http.start(conversationID: settings.recentConversation(), events: events)
                needsSignIn = false
                return use(http)
            } catch let failure as AskClient.Failure {
                if failure.signedOut {
                    secrets.delete(SecretAccount.session)
                    needsSignIn = true
                }
                notice = failure.message
                return nil
            } catch {
                notice = error.localizedDescription
                return nil
            }
        }
        needsSignIn = true
        notice = "Live voice is not available on this server yet (\(liveProblem ?? "no answer")). "
            + "Sign in with your Ira email and password to talk by typing and by voice."
        return nil
    }

    private func use(_ transport: VoiceTransport) -> VoiceTransport {
        self.transport = transport
        transportKind = transport.kind
        notice = nil
        return transport
    }

    /// Close the connection (the window closed, or the person signed out).
    func disconnect() {
        stopListening()
        audio.stopPlayback()
        transport?.close()
        transport = nil
        transportKind = nil
    }

    // MARK: Typing

    func send(_ text: String) {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        lastInputWasVoice = false
        let entry = Entry(role: .you, text: text)
        typed = (entry.id, text)
        entries.append(entry)
        mode = .thinking
        Task {
            guard let transport = await connect() else {
                mode = .idle
                return
            }
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
            if let conversationID { settings.rememberConversation(conversationID) }
            if let assistant, !assistant.isEmpty { settings.assistantName = assistant }
        case .partial(let text):
            caption = text
        case .heard(let turn, let text):
            caption = ""
            if let typed, typed.text == text, let index = entries.firstIndex(where: { $0.id == typed.id }) {
                entries[index].turn = turn
            } else {
                entries.append(Entry(role: .you, text: text, turn: turn))
            }
            typed = nil
            mode = .thinking
        case .tool(_, let name):
            caption = Conversation.phrase(name)
        case .delta(let turn, let text):
            caption = ""
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
            caption = ""
            if mode == .thinking { mode = listening ? .listening : .idle }
            lastActivity = Date()
        case .interrupted(let turn):
            interruptedTurn = max(interruptedTurn, turn)
        case .error(let message, let fatal):
            notice = message
            if mode == .thinking { mode = listening ? .listening : .idle }
            if fatal { disconnect() }
        case .closed(let reason):
            transport = nil
            transportKind = nil
            if listening {
                stopListening()
                notice = "The connection to Ira closed\(reason.map { " (\($0))" } ?? ""). Press the mic to talk again."
            }
        }
    }

    static func phrase(_ tool: String) -> String {
        switch tool {
        case "files_find": return "Looking for files…"
        case "file_read": return "Reading the file…"
        case "file_open": return "Opening it…"
        case "screen_read": return "Reading your screen…"
        default: return "Working…"
        }
    }

    func clear() {
        entries.removeAll()
        settings.rememberConversation(nil)
        disconnect()
    }
}
