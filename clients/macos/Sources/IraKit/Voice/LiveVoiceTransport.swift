import Foundation

/// The live voice protocol, version 1 (docs/realtime.md).
public enum LiveProtocol {
    public static let version = 1
    public static let path = "/v1/voice/live"

    /// A message from the server.
    public enum Incoming: Equatable, Sendable {
        case ready(conversationID: String?, assistant: String?, languages: [String], tts: String?)
        case partial(text: String, language: String?)
        case heard(turn: Int, text: String, language: String?)
        case delta(turn: Int, text: String)
        /// The next binary frame is this sentence's audio.
        case audio(turn: Int, seq: Int, text: String, format: String, bytes: Int?)
        case action(turn: Int, action: JSONValue)
        case done(turn: Int, text: String, messageID: Int?, timings: JSONValue?)
        case interrupted(turn: Int)
        case ping
        case error(message: String, fatal: Bool)
        case other(String)
    }

    public struct BadMessage: Error, Equatable {}

    public static func decode(_ text: String) throws -> Incoming {
        guard let message = JSONValue.parse(text), let type = message["type"]?.stringValue else {
            throw BadMessage()
        }
        let turn = message["turn"]?.intValue ?? 0
        switch type {
        case "ready":
            return .ready(
                conversationID: message["conversation_id"]?.stringValue,
                assistant: message["assistant"]?.stringValue,
                languages: (message["languages"]?.arrayValue ?? []).compactMap(\.stringValue),
                tts: message["tts"]?.stringValue)
        case "partial":
            return .partial(text: message["text"]?.stringValue ?? "", language: message["language"]?.stringValue)
        case "heard":
            return .heard(turn: turn, text: message["text"]?.stringValue ?? "", language: message["language"]?.stringValue)
        case "delta":
            return .delta(turn: turn, text: message["text"]?.stringValue ?? "")
        case "audio":
            return .audio(
                turn: turn, seq: message["seq"]?.intValue ?? 0, text: message["text"]?.stringValue ?? "",
                format: message["format"]?.stringValue ?? "mp3", bytes: message["bytes"]?.intValue)
        case "action":
            return .action(turn: turn, action: message["action"] ?? .object([:]))
        case "done":
            return .done(
                turn: turn, text: message["text"]?.stringValue ?? "",
                messageID: message["message_id"]?.intValue, timings: message["timings"])
        case "interrupted":
            return .interrupted(turn: turn)
        case "ping":
            return .ping
        case "error":
            return .error(
                message: message["message"]?.stringValue ?? "something went wrong",
                fatal: message["fatal"]?.boolValue ?? false)
        default:
            return .other(type)
        }
    }

    public static func start(conversationID: String?) -> JSONValue {
        var message: [String: JSONValue] = [
            "type": "start", "protocol": .number(Double(version)), "client": .string(IraApp.userAgent),
        ]
        if let conversationID { message["conversation_id"] = .string(conversationID) }
        return .object(message)
    }

    public static func speechStart(at: Double) -> JSONValue { ["type": "speech_start", "at": .number(rounded(at))] }
    public static func speechEnd(at: Double) -> JSONValue { ["type": "speech_end", "at": .number(rounded(at))] }
    public static func text(_ text: String) -> JSONValue { ["type": "text", "text": .string(text)] }
    public static let interrupt: JSONValue = ["type": "interrupt"]
    public static func played(turn: Int, at: Double) -> JSONValue {
        ["type": "played", "turn": .number(Double(turn)), "at": .number(rounded(at))]
    }
    public static let pong: JSONValue = ["type": "pong"]
    public static let bye: JSONValue = ["type": "bye"]

    static func rounded(_ value: Double) -> Double { (value * 10).rounded() / 10 }
}

/// The live connection could not start: no such route, or the server cannot do live voice.
public struct LiveUnavailable: LocalizedError, Equatable {
    public let message: String
    public init(_ message: String) { self.message = message }
    public var errorDescription: String? { message }
}

/// Live voice over `/v1/voice/live`, signed in with this Mac's device token.
public final class LiveVoiceTransport: VoiceTransport, @unchecked Sendable {
    public let kind = "live"
    private let url: URL
    private let token: String
    private let connector: WebSocketConnector
    private let readyTimeout: Double
    private let log: IraLog

    private let lock = NSLock()
    private var channel: WebSocketChannel?
    private var outbox: AsyncStream<WebSocketMessage>.Continuation?
    private var tasks: [Task<Void, Never>] = []
    private var closed = false

    /// Audio frames go up in 20-100 ms pieces: whole 20 ms frames are 640 bytes.
    public static let maxAudioFrame = 3_200

    public init(
        server: String, token: String, connector: WebSocketConnector = URLSessionWebSocketConnector(),
        readyTimeout: Double = 15, log: IraLog = .shared
    ) throws {
        guard let url = Pairing.websocketURL(server: server, path: LiveProtocol.path) else {
            throw LiveUnavailable("the server address must start with http:// or https://")
        }
        self.url = url
        self.token = token
        self.connector = connector
        self.readyTimeout = readyTimeout
        self.log = log
    }

    public func start(conversationID: String?, events: @escaping @Sendable (TalkEvent) -> Void) async throws {
        let channel: WebSocketChannel
        do {
            channel = try await connector.connect(
                url: url, headers: ["Authorization": "Bearer \(token)", "User-Agent": IraApp.userAgent])
        } catch {
            throw LiveUnavailable("could not reach live voice: \(Pairing.reason(error))")
        }
        do {
            try await channel.send(.text(LiveProtocol.start(conversationID: conversationID).encoded()))
            let first = try await withTimeout(readyTimeout) { try await channel.receive() }
            guard case .text(let text) = first else { throw LiveUnavailable("live voice did not start") }
            switch try LiveProtocol.decode(text) {
            case .ready(let conversation, let assistant, _, _):
                events(.ready(conversationID: conversation, assistant: assistant))
            case .error(let message, _):
                throw LiveUnavailable(message)
            default:
                throw LiveUnavailable("live voice did not start")
            }
        } catch let unavailable as LiveUnavailable {
            channel.close(code: 1000)
            throw unavailable
        } catch let closedError as WebSocketClosed {
            channel.close(code: 1000)
            if closedError.httpStatus == 404 { throw LiveUnavailable("this Ira server has no live voice yet") }
            if closedError.unauthorized { throw LiveUnavailable("the server refused this Mac's key for live voice") }
            let status = closedError.httpStatus.map { " (HTTP \($0))" } ?? ""
            throw LiveUnavailable("live voice did not start: \(closedError.reason)\(status)")
        } catch {
            channel.close(code: 1000)
            throw LiveUnavailable("live voice did not start")
        }

        let (stream, continuation) = AsyncStream<WebSocketMessage>.makeStream(bufferingPolicy: .bufferingNewest(500))
        lock.locked {
            self.channel = channel
            self.outbox = continuation
        }

        let sender = Task {
            for await message in stream {
                do { try await channel.send(message) } catch { break }
            }
        }
        let reader = Task { [weak self] in
            guard let self else { return }
            await self.read(channel, events: events)
        }
        lock.locked { tasks = [sender, reader] }
    }

    private func read(_ channel: WebSocketChannel, events: @escaping @Sendable (TalkEvent) -> Void) async {
        var pendingAudio: (turn: Int, seq: Int, text: String)?
        while true {
            let message: WebSocketMessage
            do {
                message = try await channel.receive()
            } catch {
                let reason = (error as? WebSocketClosed)?.reason
                if !isClosed { events(.closed(reason)) }
                return
            }
            switch message {
            case .data(let data):
                if let audio = pendingAudio {
                    pendingAudio = nil
                    events(.audio(turn: audio.turn, seq: audio.seq, text: audio.text, data: data))
                }
            case .text(let text):
                guard let incoming = try? LiveProtocol.decode(text) else { continue }
                switch incoming {
                case .ready(let conversation, let assistant, _, _):
                    events(.ready(conversationID: conversation, assistant: assistant))
                case .partial(let text, _):
                    events(.partial(text))
                case .heard(let turn, let text, _):
                    events(.heard(turn: turn, text: text))
                case .delta(let turn, let text):
                    events(.delta(turn: turn, text: text))
                case .audio(let turn, let seq, let text, _, _):
                    pendingAudio = (turn, seq, text)
                case .action(let turn, let action):
                    events(.action(turn: turn, action: action))
                case .done(let turn, let text, _, _):
                    events(.done(turn: turn, text: text))
                case .interrupted(let turn):
                    pendingAudio = nil
                    events(.interrupted(turn: turn))
                case .ping:
                    send(LiveProtocol.pong)
                case .error(let message, let fatal):
                    events(.error(message, fatal: fatal))
                case .other:
                    break
                }
            }
        }
    }

    private var isClosed: Bool {
        lock.locked { closed }
    }

    private func send(_ message: JSONValue) {
        enqueue(.text(message.encoded()))
    }

    private func enqueue(_ message: WebSocketMessage) {
        lock.lock()
        let outbox = closed ? nil : self.outbox
        lock.unlock()
        outbox?.yield(message)
    }

    public func speechStart(at: Double) { send(LiveProtocol.speechStart(at: at)) }

    public func audio(_ pcm: Data) {
        var offset = 0
        while offset < pcm.count {
            let end = min(offset + LiveVoiceTransport.maxAudioFrame, pcm.count)
            enqueue(.data(pcm.subdata(in: offset..<end)))
            offset = end
        }
    }

    public func speechEnd(at: Double) { send(LiveProtocol.speechEnd(at: at)) }
    public func text(_ text: String) { send(LiveProtocol.text(text)) }
    public func interrupt() { send(LiveProtocol.interrupt) }
    public func played(turn: Int, at: Double) { send(LiveProtocol.played(turn: turn, at: at)) }

    public func close() {
        lock.lock()
        guard !closed else {
            lock.unlock()
            return
        }
        let outbox = self.outbox
        let channel = self.channel
        let tasks = self.tasks
        lock.unlock()
        // Say goodbye first, then stop.
        outbox?.yield(.text(LiveProtocol.bye.encoded()))
        lock.lock()
        closed = true
        lock.unlock()
        outbox?.finish()
        Task {
            try? await Task.sleep(nanoseconds: 300_000_000)
            channel?.close(code: 1000)
            tasks.forEach { $0.cancel() }
        }
        log.info("live voice closed")
    }
}
