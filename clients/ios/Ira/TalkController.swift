import IraPhoneKit
import Observation
import UIKit

/// The conversation: typing, calls, Ira's answers and her proposals.
///
/// A call is a **live call** over `/v1/voice/live` when the server has live
/// voice: the iPhone's voice detector sends audio from the lead-in before
/// speech until `speech_end`, Ira answers sentence by sentence, and speaking
/// over her stops her at once. Otherwise it is **phone mode**: the iPhone's own
/// speech recognition turns each spoken turn into text, which goes to
/// `/v1/ask/stream`, and the answer is spoken by the server's voice or the
/// iPhone's. Typing works in both, and without a call.
@MainActor
@Observable
final class TalkController {
    enum CallState: Equatable {
        case idle
        case connecting
        /// A call is on: Ira listens; `hearing` while the person speaks.
        case listening(hearing: Bool)
    }

    weak var model: AppModel?
    private let settings: AppSettings

    private(set) var transcript = Transcript()
    private(set) var callState: CallState = .idle
    /// How this call talks to Ira, for the line under the call button.
    private(set) var mode: TalkMode?
    /// A live caption of what the person is saying.
    private(set) var caption = ""
    /// What Ira is doing for the question on its way: "Checking your calendar…".
    private(set) var step: String?
    private(set) var stepStarted: Date?
    /// Ira is talking.
    private(set) var speaking = false
    /// The microphone's level, 0 to 1, for the call button.
    private(set) var level: Float = 0
    /// What came of answering a proposal, by its id.
    private(set) var outcomes: [String: String] = [:]
    /// A proposal being answered now.
    private(set) var deciding: Set<String> = []

    private let audio = AudioEngine()
    private var vad = EnergyVAD()
    private var live: LiveVoiceTransport?
    private var recognizer: PhoneRecognizer?
    private var asking: AskSession?
    private var askingServer = ""
    /// Each live call numbers its turns from 1; typing and phone mode share source 0.
    private var source = 0
    private var calls = 0
    private var stoppedThrough = 0
    private var lastTurn = 0
    private var lastActivity = Date()
    private var idleTimer: Timer?
    private var phoneTurnBusy = false

    var inCall: Bool { callState != .idle }

    init(settings: AppSettings) {
        self.settings = settings
        audio.onFrame = { [weak self] samples, at in self?.frame(samples, at: at) }
        audio.onTurnStarted = { [weak self] turn in
            guard let self else { return }
            self.speaking = true
            self.live?.played(turn: turn, at: monotonicMs())
        }
        audio.onIdle = { [weak self] in
            guard let self else { return }
            self.speaking = false
            self.vad.replying = false
            self.lastActivity = Date()
        }
        audio.onInterrupted = { [weak self] message in
            self?.endCall()
            self?.model?.notice = message
        }
    }

    // MARK: Showing what Ira is doing

    private func began(_ words: String) {
        step = words
        stepStarted = Date()
    }

    private func finished() {
        step = nil
        stepStarted = nil
    }

    private var notice: String? {
        get { model?.notice }
        set { model?.notice = newValue }
    }

    // MARK: Typing

    private func askSession() -> AskSession? {
        guard let model, let client = model.client() else { return nil }
        if let asking, askingServer == client.server { return asking }
        let session = AskSession(client: client, serverSpeaks: model.info?.speaks ?? false)
        asking = session
        askingServer = client.server
        return session
    }

    /// A typed turn: into the call when one is live, else over `/v1/ask/stream`.
    func send(_ text: String) {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        notice = nil
        lastActivity = Date()
        if let live {
            stopSpeaking()
            transcript.said(text, source: source)
            began(StepWords.thinking)
            live.text(text)
            return
        }
        guard let asking = askSession() else {
            notice = "This iPhone is not paired with your Ira yet. Pair it in Get Ira ready."
            return
        }
        if speaking { stopSpeaking() }
        // A typed question is answered on screen; during a phone-mode call it is spoken too.
        let spoken = inCall
        let turn = asking.ask(text, conversationID: settings.conversationID, spoken: spoken) { event in
            Task { @MainActor [weak self] in self?.handle(event, source: 0) }
        }
        lastTurn = turn
        transcript.said(text, source: 0, turn: turn)
        began(StepWords.thinking)
    }

    // MARK: Calls

    func toggleCall() {
        inCall ? endCall() : startCall()
    }

    func startCall() {
        guard !inCall, let model else { return }
        notice = nil
        callState = .connecting
        began(StepWords.connecting)
        Task { await self.connect(model) }
    }

    private func connect(_ model: AppModel) async {
        switch model.permissions.state(.microphone) {
        case .allowed: break
        case .notAsked:
            if await model.permissions.request(.microphone) != .allowed {
                return refuse("Ira cannot hear you: the microphone is off for Ira. Switch it on in the iPhone's Settings, Ira, Microphone.")
            }
        default:
            return refuse("Ira cannot hear you: the microphone is off for Ira. Switch it on in the iPhone's Settings, Ira, Microphone.")
        }
        guard let info = await model.loadInfo() ?? model.info else {
            return refuse(model.notice ?? "Your Ira cannot be reached right now. Check that your iPhone is online, then try again.")
        }
        guard info.canAsk else { return refuse(model.notice ?? "Your Ira account may not talk to Ira.") }
        guard let token = model.record.token else { return refuse(PairingRecord.unreadable) }
        var fallback: String?
        if info.live {
            do {
                try await startLive(server: model.settings.server, token: token)
                return
            } catch {
                fallback = "Live calls did not start (\(error.localizedDescription)), so the iPhone recognises your speech instead."
            }
        }
        await startPhone(info: info, model: model, note: fallback)
    }

    private func refuse(_ message: String) {
        callState = .idle
        finished()
        notice = message
    }

    private func startLive(server: String, token: String) async throws {
        let transport = try LiveVoiceTransport(server: server, token: token)
        calls += 1
        let source = 1000 + calls
        try await transport.start(conversationID: settings.conversationID) { event in
            Task { @MainActor [weak self] in self?.handle(event, source: source) }
        }
        self.source = source
        live = transport
        stoppedThrough = 0
        do {
            try beginListening()
        } catch {
            transport.close()
            live = nil
            throw error
        }
        mode = .live
    }

    private func startPhone(info: ServerInfo, model: AppModel, note: String?) async {
        switch model.permissions.state(.speech) {
        case .allowed: break
        case .notAsked:
            if await model.permissions.request(.speech) != .allowed {
                return refuse("Your Ira has no live calls, and speech recognition is off for Ira. Switch it on in the iPhone's Settings, Ira, Speech Recognition, or type.")
            }
        default:
            return refuse("Your Ira has no live calls, and speech recognition is off for Ira. Switch it on in the iPhone's Settings, Ira, Speech Recognition, or type.")
        }
        do {
            recognizer = try PhoneRecognizer(preferred: info.micLanguage)
            source = 0
            try beginListening()
            mode = .phone(serverVoice: info.speaks)
            notice = note
        } catch {
            recognizer = nil
            refuse((error as? PhoneRecognizer.Unavailable)?.message ?? "The microphone did not start: \(error.localizedDescription). Try again.")
        }
    }

    private func beginListening() throws {
        try audio.activateSession()
        audio.newCall()
        vad = EnergyVAD()
        try audio.startListening()
        callState = .listening(hearing: false)
        finished()
        lastActivity = Date()
        UIApplication.shared.isIdleTimerDisabled = true
        startIdleTimer()
    }

    func endCall() {
        guard inCall || live != nil || recognizer != nil else { return }
        if vad.speaking { live?.speechEnd(at: monotonicMs()) }
        live?.close()
        live = nil
        recognizer?.cancel()
        recognizer = nil
        phoneTurnBusy = false
        audio.shutDown()
        vad.reset()
        callState = .idle
        mode = nil
        caption = ""
        level = 0
        speaking = false
        idleTimer?.invalidate()
        idleTimer = nil
        UIApplication.shared.isIdleTimerDisabled = false
        if step == StepWords.connecting || step == StepWords.listening { finished() }
    }

    /// Stop Ira talking, and the answer on its way (the Stop button).
    func stop() {
        stopSpeaking()
        live?.interrupt()
        asking?.interrupt { event in Task { @MainActor [weak self] in self?.handle(event, source: 0) } }
        finished()
    }

    private func stopSpeaking() {
        let turn = max(lastTurn, stoppedThrough)
        stoppedThrough = turn
        audio.stopPlayback(through: turn)
        speaking = false
        vad.replying = false
    }

    private func startIdleTimer() {
        idleTimer?.invalidate()
        idleTimer = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self, self.inCall else { return }
                if let started = self.stepStarted, Date().timeIntervalSince(started) > 60 {
                    self.finished()
                    self.notice = "No answer yet: your Ira is slow or unreachable. Say it again, or tap Stop."
                }
                // Two quiet minutes with nothing on its way end the call.
                if Date().timeIntervalSince(self.lastActivity) > 120, self.step == nil, !self.speaking {
                    self.endCall()
                    self.notice = "The call ended after two quiet minutes. Tap Call to talk again."
                }
            }
        }
    }

    // MARK: The microphone

    private func frame(_ samples: [Float], at: Double) {
        guard inCall else { return }
        if recognizer != nil {
            phoneFrame(samples, at: at)
            return
        }
        vad.replying = speaking
        for output in vad.process(samples, at: at) {
            switch output {
            case .speechStart(let start):
                if speaking {
                    // Barge-in: stop at once, without waiting for the server.
                    stopSpeaking()
                }
                callState = .listening(hearing: true)
                lastActivity = Date()
                live?.speechStart(at: start)
            case .audio(let pcm):
                live?.audio(pcm)
            case .speechEnd(let end):
                live?.speechEnd(at: end)
                callState = .listening(hearing: false)
                lastActivity = Date()
                began(StepWords.thinking)
            }
        }
        level = vad.level
    }

    /// Phone mode: the iPhone hears one turn while Ira is quiet; no barge-in
    /// (her voice would be heard as speech), so Stop interrupts her.
    private func phoneFrame(_ samples: [Float], at: Double) {
        guard let recognizer, !phoneTurnBusy, !speaking, step == nil else {
            level = 0
            return
        }
        for output in vad.process(samples, at: at) {
            switch output {
            case .speechStart:
                recognizer.begin()
                callState = .listening(hearing: true)
                lastActivity = Date()
            case .audio(let pcm):
                recognizer.append(PCM.floats(pcm))
                caption = recognizer.partial
            case .speechEnd:
                callState = .listening(hearing: false)
                phoneTurnBusy = true
                began("Recognising what you said…")
                Task { await self.finishPhoneTurn(recognizer) }
            }
        }
        level = vad.level
    }

    private func finishPhoneTurn(_ recognizer: PhoneRecognizer) async {
        let heard = await recognizer.end()
        caption = ""
        phoneTurnBusy = false
        guard inCall else { return }
        guard !heard.isEmpty else {
            finished()
            notice = "I didn't catch that. Say it again, a little closer to the iPhone."
            return
        }
        notice = nil
        guard let asking = askSession() else { return finished() }
        let turn = asking.ask(heard, conversationID: settings.conversationID, spoken: true) { event in
            Task { @MainActor [weak self] in self?.handle(event, source: 0) }
        }
        lastTurn = turn
        transcript.said(heard, source: 0, turn: turn)
        began(StepWords.thinking)
    }

    // MARK: Ira's answers

    private func handle(_ event: TalkEvent, source: Int) {
        lastActivity = Date()
        transcript.apply(event, source: source)
        switch event {
        case .ready(let conversationID, _):
            if let conversationID { settings.adoptConversation(conversationID) }
        case .partial(let text):
            caption = text
        case .heard(let turn, _):
            caption = ""
            lastTurn = max(lastTurn, turn)
            began(StepWords.thinking)
        case .tool(_, let name):
            began(StepWords.tool(name))
        case .delta:
            caption = ""
        case .audio(let turn, let seq, _, let data):
            guard inCall, turn > stoppedThrough else { return }
            vad.replying = true
            audio.play(mp3: data, turn: turn, seq: seq)
        case .say(let turn, let seq, let text):
            guard inCall, turn > stoppedThrough else { return }
            vad.replying = true
            audio.say(text, turn: turn, seq: seq)
        case .action:
            break
        case .done:
            finished()
        case .interrupted(let turn):
            stoppedThrough = max(stoppedThrough, turn)
            audio.stopPlayback(through: turn)
            finished()
        case .error(let message, let fatal):
            finished()
            if fatal, source != 0 {
                endCall()
                notice = Plain.sentence(message)
            } else if fatal {
                notice = "Your Ira no longer knows this iPhone (it was removed on Your devices). Pair it again in Settings."
                model?.refreshPairing()
            }
        case .closed(let reason):
            guard source == self.source, live != nil else { return }
            endCall()
            finished()
            notice = "The call dropped\(reason.map { " (\($0))" } ?? ""). Tap Call to talk again."
        }
    }

    // MARK: Proposals

    /// Yes or No to a Tier 2 proposal: `/v1/actions/{id}/approve` or `/cancel`.
    func answer(_ card: ActionCard, yes: Bool) {
        guard let client = model?.client() else { return }
        deciding.insert(card.id)
        Task {
            defer { deciding.remove(card.id) }
            do {
                let outcome = yes ? try await client.approve(actionID: card.id) : try await client.cancel(actionID: card.id)
                settle(card, outcome)
            } catch {
                outcomes[card.id] = (error as? AskClient.Failure)?.message ?? error.localizedDescription
            }
        }
    }

    /// Confirm a Tier 3 proposal with the PIN typed here. The PIN goes only to
    /// `/v1/actions/{id}/confirm`, never into the conversation, and is not kept.
    func confirm(_ card: ActionCard, pin: String) {
        let pin = pin.filter(\.isNumber)
        guard (4...12).contains(pin.count) else {
            outcomes[card.id] = "Your PIN is 4 to 12 digits."
            return
        }
        guard let client = model?.client() else { return }
        deciding.insert(card.id)
        Task {
            defer { deciding.remove(card.id) }
            do {
                settle(card, try await client.confirm(actionID: card.id, pin: pin))
            } catch {
                outcomes[card.id] = (error as? AskClient.Failure)?.message ?? error.localizedDescription
            }
        }
    }

    private func settle(_ card: ActionCard, _ outcome: ActionOutcome) {
        if let status = outcome.cardStatus { transcript.settle(actionID: card.id, status: status) }
        outcomes[card.id] = outcome.sentence
    }

    // MARK: Reports

    /// Report one of Ira's answers. Returns nil when sent, else what to tell the person.
    func report(_ entry: Entry, reason: ReportReason, note: String) async -> String? {
        guard let messageID = entry.messageID, let client = model?.client() else {
            return "This answer cannot be reported."
        }
        do {
            try await client.report(messageID: messageID, reason: reason, note: note)
            transcript.markReported(entry.id)
            return nil
        } catch {
            return (error as? AskClient.Failure)?.message ?? error.localizedDescription
        }
    }

    // MARK: Starting over

    func newConversation() {
        endCall()
        asking?.interrupt()
        settings.newConversation()
        transcript.clear()
        outcomes.removeAll()
        finished()
    }

    /// Paired again or removed: forget everything of the old pairing.
    func reset() {
        newConversation()
        asking = nil
        askingServer = ""
    }
}
