import Foundation

/// Voice over the plain HTTP API, for servers without live voice: the spoken
/// turn is recorded, sent to `/v1/voice/transcribe`, asked through
/// `/v1/ask/stream`, and each sentence of the answer is spoken through
/// `/v1/voice/speak` as soon as it is complete. Typing uses the same stream.
public final class HTTPVoiceTransport: VoiceTransport, @unchecked Sendable {
    public let kind = "http"
    private let client: AskClient
    private let speakReplies: @Sendable () -> Bool

    private let lock = NSLock()
    private var events: (@Sendable (TalkEvent) -> Void)?
    private var conversationID: String?
    private var recording: Data?
    private var turn = 0
    private var current: Task<Void, Never>?
    private var currentTurn: Int?
    private var serverSpeaks = true
    /// The most audio one spoken turn may carry: the server takes 10 MB.
    static let maxRecording = 9 * 1024 * 1024

    public init(client: AskClient, speakReplies: @escaping @Sendable () -> Bool) {
        self.client = client
        self.speakReplies = speakReplies
    }

    public func start(conversationID: String?, events: @escaping @Sendable (TalkEvent) -> Void) async throws {
        let info: JSONValue
        do {
            info = try await client.info()
        } catch let failure as AskClient.Failure {
            if failure.signedOut { throw AskClient.Failure("sign in again to talk to Ira", status: 401) }
            throw failure
        }
        let permissions = (info["permissions"]?.arrayValue ?? []).compactMap(\.stringValue)
        guard permissions.contains("ask") else {
            throw AskClient.Failure("this account may not talk to Ira (it has no ask permission)", status: 403)
        }
        let tts = info["tts"]?.stringValue
        lock.locked {
            self.events = events
            self.conversationID = conversationID
            serverSpeaks = permissions.contains("voice") && tts != nil && tts != "fake"
        }
        events(.ready(conversationID: conversationID, assistant: info["name"]?.stringValue))
    }

    private func emit(_ event: TalkEvent) {
        lock.lock()
        let events = self.events
        lock.unlock()
        events?(event)
    }

    public func speechStart(at: Double) {
        interrupt()
        lock.lock()
        recording = Data()
        lock.unlock()
    }

    public func audio(_ pcm: Data) {
        lock.lock()
        if var recording, recording.count + pcm.count <= HTTPVoiceTransport.maxRecording {
            recording.append(pcm)
            self.recording = recording
        }
        lock.unlock()
    }

    public func speechEnd(at: Double) {
        lock.lock()
        let pcm = recording
        recording = nil
        turn += 1
        let turn = self.turn
        lock.unlock()
        guard let pcm, !pcm.isEmpty else { return }
        run(turn) { [client] in
            let text = try await client.transcribe(wav: PCM.wav(pcm))
            let heard = text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !heard.isEmpty else {
                self.emit(.error("I didn't catch that.", fatal: false))
                return
            }
            self.emit(.heard(turn: turn, text: heard))
            try await self.ask(heard, turn: turn, spoken: true)
        }
    }

    public func text(_ text: String) {
        interrupt()
        lock.lock()
        turn += 1
        let turn = self.turn
        lock.unlock()
        run(turn) { try await self.ask(text, turn: turn, spoken: false) }
    }

    private func run(_ turn: Int, _ work: @escaping @Sendable () async throws -> Void) {
        lock.lock()
        let task = Task {
            do {
                try await work()
            } catch is CancellationError {
            } catch let failure as AskClient.Failure {
                self.emit(.error(failure.message, fatal: failure.signedOut))
            } catch {
                self.emit(.error(error.localizedDescription, fatal: false))
            }
            self.finished(turn)
        }
        current = task
        currentTurn = turn
        lock.unlock()
    }

    private func finished(_ turn: Int) {
        lock.lock()
        if currentTurn == turn {
            current = nil
            currentTurn = nil
        }
        lock.unlock()
    }

    private func ask(_ text: String, turn: Int, spoken: Bool) async throws {
        let (conversation, serverSpeaks) = lock.locked { (conversationID, self.serverSpeaks) }
        let speak = spoken || speakReplies()
        var splitter = SentenceSplitter()
        var seq = 0
        let chain = SpeechChain()

        func say(_ sentence: String) {
            let number = seq
            seq += 1
            guard serverSpeaks else {
                emit(.say(turn: turn, seq: number, text: sentence))
                return
            }
            // Fetch now, deliver in order.
            let fetch = Task { try? await self.client.speak(sentence) }
            chain.append { previous in
                Task {
                    await previous?.value
                    let audio = await fetch.value
                    if Task.isCancelled { return }
                    if let audio, !audio.isEmpty {
                        self.emit(.audio(turn: turn, seq: number, text: sentence, data: audio))
                    } else {
                        self.emit(.say(turn: turn, seq: number, text: sentence))
                    }
                }
            }
        }

        var full = ""
        try await withTaskCancellationHandler {
            for try await event in client.askStream(text, conversationID: conversation) {
                try Task.checkCancellation()
                switch event["type"]?.stringValue {
                case "start":
                    if let id = event["conversation_id"]?.stringValue {
                        lock.locked { conversationID = id }
                        emit(.ready(conversationID: id, assistant: nil))
                    }
                case "tool":
                    emit(.tool(turn: turn, name: event["name"]?.stringValue ?? ""))
                case "delta":
                    let piece = event["text"]?.stringValue ?? ""
                    full += piece
                    emit(.delta(turn: turn, text: piece))
                    if speak { splitter.feed(piece).forEach(say) }
                case "action":
                    if let action = event["action"] { emit(.action(turn: turn, action: action)) }
                case "error":
                    emit(.error(event["message"]?.stringValue ?? "no model could answer", fatal: false))
                case "done":
                    let final = event["text"]?.stringValue ?? full
                    if speak {
                        if full.isEmpty { splitter.feed(final).forEach(say) }
                        if let rest = splitter.flush() { say(rest) }
                    }
                    emit(.done(turn: turn, text: final.isEmpty ? full : final))
                default:
                    break
                }
            }
            await chain.wait()
        } onCancel: {
            chain.cancel()
        }
    }

    public func interrupt() {
        lock.lock()
        let task = current
        let turn = currentTurn
        current = nil
        currentTurn = nil
        lock.unlock()
        if let task, let turn {
            task.cancel()
            emit(.interrupted(turn: turn))
        }
    }

    public func played(turn: Int, at: Double) {}

    public func close() {
        lock.lock()
        let task = current
        current = nil
        events = nil
        lock.unlock()
        task?.cancel()
    }
}

/// The spoken sentences of one answer, delivered one after another.
final class SpeechChain: @unchecked Sendable {
    private let lock = NSLock()
    private var last: Task<Void, Never>?
    private var all: [Task<Void, Never>] = []

    func append(_ make: (Task<Void, Never>?) -> Task<Void, Never>) {
        lock.lock()
        let task = make(last)
        last = task
        all.append(task)
        lock.unlock()
    }

    func wait() async {
        let last = lock.locked { self.last }
        await last?.value
    }

    func cancel() {
        lock.lock()
        let all = self.all
        lock.unlock()
        all.forEach { $0.cancel() }
    }
}
