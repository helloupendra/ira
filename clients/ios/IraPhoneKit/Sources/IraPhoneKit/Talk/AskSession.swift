import Foundation

/// Asking over HTTP: typing, and the phone mode of a call (the iPhone recognised
/// the words). The question goes to `POST /v1/ask/stream`; the answer streams
/// back as `TalkEvent`s, and when it should be spoken, each sentence is fetched
/// from `/v1/voice/speak` as soon as it is complete, or handed to the iPhone's
/// own voice when the server has none. Sentences arrive in order.
public final class AskSession: @unchecked Sendable {
    private let client: AskClient
    private let serverSpeaks: Bool
    private let lock = NSLock()
    private var turn = 0
    private var current: (turn: Int, task: Task<Void, Never>)?

    public init(client: AskClient, serverSpeaks: Bool) {
        self.client = client
        self.serverSpeaks = serverSpeaks
    }

    /// Ask; returns the turn number. A question still running is stopped first.
    @discardableResult
    public func ask(
        _ text: String, conversationID: String?, spoken: Bool, events: @escaping @Sendable (TalkEvent) -> Void
    ) -> Int {
        interrupt(events: events)
        let turn = lock.withLock {
            self.turn += 1
            return self.turn
        }
        let task = Task { [client, serverSpeaks] in
            do {
                try await AskSession.run(
                    client: client, text: text, conversationID: conversationID, turn: turn, spoken: spoken,
                    serverSpeaks: serverSpeaks, events: events)
            } catch is CancellationError {
            } catch let failure as AskClient.Failure {
                events(.error(failure.message, fatal: failure.signedOut))
            } catch {
                events(.error(error.localizedDescription, fatal: false))
            }
            self.finished(turn)
        }
        lock.withLock { current = (turn, task) }
        return turn
    }

    private func finished(_ turn: Int) {
        lock.withLock {
            if current?.turn == turn { current = nil }
        }
    }

    /// Stop the answer on its way (Stop, or a new question).
    public func interrupt(events: (@Sendable (TalkEvent) -> Void)? = nil) {
        let running = lock.withLock {
            let running = current
            current = nil
            return running
        }
        if let running {
            running.task.cancel()
            events?(.interrupted(turn: running.turn))
        }
    }

    public var isAnswering: Bool { lock.withLock { current != nil } }

    static func run(
        client: AskClient, text: String, conversationID: String?, turn: Int, spoken: Bool,
        serverSpeaks: Bool, events: @escaping @Sendable (TalkEvent) -> Void
    ) async throws {
        var splitter = SentenceSplitter()
        var seq = 0
        let chain = SpeechChain()

        func say(_ sentence: String) {
            let number = seq
            seq += 1
            guard serverSpeaks else {
                chain.append { previous in
                    Task {
                        await previous?.value
                        if !Task.isCancelled { events(.say(turn: turn, seq: number, text: sentence)) }
                    }
                }
                return
            }
            // Fetch now, deliver in order; a sentence the server cannot speak is said by the iPhone.
            let fetch = Task { try? await client.speak(sentence) }
            chain.append { previous in
                Task {
                    await previous?.value
                    let audio = await fetch.value
                    if Task.isCancelled { return }
                    if let audio, !audio.isEmpty {
                        events(.audio(turn: turn, seq: number, text: sentence, data: audio))
                    } else {
                        events(.say(turn: turn, seq: number, text: sentence))
                    }
                }
            }
        }

        var full = ""
        try await withTaskCancellationHandler {
            for try await event in client.askStream(text, conversationID: conversationID) {
                try Task.checkCancellation()
                switch event {
                case .start(let id):
                    if !id.isEmpty { events(.ready(conversationID: id, assistant: nil)) }
                case .tool(_, let name):
                    events(.tool(turn: turn, name: name))
                case .toolResult, .other:
                    break
                case .delta(let piece):
                    full += piece
                    events(.delta(turn: turn, text: piece))
                    if spoken { splitter.feed(piece).forEach(say) }
                case .action(let card):
                    events(.action(turn: turn, action: card))
                case .error(let message):
                    events(.error(message, fatal: false))
                case .done(let final, let id, let messageID):
                    if let id, !id.isEmpty { events(.ready(conversationID: id, assistant: nil)) }
                    if spoken {
                        // Whatever the final text holds beyond the streamed pieces is spoken too.
                        if final.hasPrefix(full) { splitter.feed(String(final.dropFirst(full.count))).forEach(say) }
                        if let rest = splitter.flush() { say(rest) }
                    }
                    events(.done(turn: turn, text: final.isEmpty ? full : final, messageID: messageID))
                }
            }
            await chain.wait()
        } onCancel: {
            chain.cancel()
        }
    }
}

/// The spoken sentences of one answer, delivered one after another.
final class SpeechChain: @unchecked Sendable {
    private let lock = NSLock()
    private var last: Task<Void, Never>?
    private var all: [Task<Void, Never>] = []

    func append(_ make: (Task<Void, Never>?) -> Task<Void, Never>) {
        lock.withLock {
            let task = make(last)
            last = task
            all.append(task)
        }
    }

    func wait() async {
        let last = lock.withLock { self.last }
        await last?.value
    }

    func cancel() {
        let all = lock.withLock { self.all }
        all.forEach { $0.cancel() }
    }
}
