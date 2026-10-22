import Foundation

/// What a conversation hears back from Ira, whichever transport carries it.
public enum TalkEvent: Equatable, Sendable {
    /// Connected; send speech or text when you like.
    case ready(conversationID: String?, assistant: String?)
    /// A live caption of what the person is saying; each replaces the last.
    case partial(String)
    /// The final text of the person's spoken turn.
    case heard(turn: Int, text: String)
    /// Ira used a tool (shown as "Looking for files…").
    case tool(turn: Int, name: String)
    /// More of the answer's text.
    case delta(turn: Int, text: String)
    /// One sentence of the answer as MP3, to play in `seq` order.
    case audio(turn: Int, seq: Int, text: String, data: Data)
    /// One sentence the server cannot speak: say it with the Mac's own voice.
    case say(turn: Int, seq: Int, text: String)
    /// A proposed action: Tier 2 needs a yes, Tier 3 the PIN in the Ira app.
    case action(turn: Int, action: JSONValue)
    /// The answer is complete.
    case done(turn: Int, text: String)
    /// No more audio for this turn (barge-in or stop).
    case interrupted(turn: Int)
    /// A turn failed; with `fatal`, the connection is closing.
    case error(String, fatal: Bool)
    case closed(String?)
}

/// How the app talks to Ira. Two implementations:
///
/// * `LiveVoiceTransport`: one WebSocket to `/v1/voice/live` (docs/realtime.md),
///   signed in with the device token. Audio goes up only while the person
///   speaks; Ira's answer comes back sentence by sentence as MP3.
/// * `HTTPVoiceTransport`: the fallback while a server has no live voice:
///   record, `/v1/voice/transcribe`, `/v1/ask/stream`, `/v1/voice/speak` per
///   sentence, with the same device token.
///
/// The conversation (microphone, voice detector, player) is the same for both.
public protocol VoiceTransport: AnyObject, Sendable {
    /// "live" or "http", for the status line.
    var kind: String { get }
    /// Connect; `events` is called for everything Ira says back, on any thread.
    func start(conversationID: String?, events: @escaping @Sendable (TalkEvent) -> Void) async throws
    /// The voice detector heard speech start (`at`: ms on the app's clock). Also a barge-in.
    func speechStart(at: Double)
    /// 20-100 ms of 16 kHz mono 16-bit PCM, only while the person speaks.
    func audio(_ pcm: Data)
    /// The person stopped; `at` is when the last spoken audio ended.
    func speechEnd(at: Double)
    /// A typed turn, in the same conversation.
    func text(_ text: String)
    /// Stop talking and stop this answer.
    func interrupt()
    /// The first audio of `turn` started playing (for the latency measure).
    func played(turn: Int, at: Double)
    func close()
}

/// The app's own clock for voice messages: milliseconds since the Mac started.
public func monotonicMs() -> Double {
    ProcessInfo.processInfo.systemUptime * 1000
}

/// Splits a streamed answer into sentences as they complete, so the first one
/// can be spoken while the rest is still being written.
public struct SentenceSplitter: Sendable {
    public var minimum = 12
    private var buffer = ""

    public init(minimum: Int = 12) {
        self.minimum = minimum
    }

    /// Add text; returns the sentences it completed.
    public mutating func feed(_ text: String) -> [String] {
        buffer += text
        var sentences: [String] = []
        while let end = nextEnd() {
            let sentence = String(buffer[..<end]).trimmingCharacters(in: .whitespacesAndNewlines)
            buffer = String(buffer[end...])
            if !sentence.isEmpty { sentences.append(sentence) }
        }
        return sentences
    }

    /// Whatever is left at the end of the answer.
    public mutating func flush() -> String? {
        let rest = buffer.trimmingCharacters(in: .whitespacesAndNewlines)
        buffer = ""
        return rest.isEmpty ? nil : rest
    }

    /// The end of the first complete sentence of at least `minimum` characters:
    /// after . ! ? or । followed by a space, or at a line break.
    private func nextEnd() -> String.Index? {
        var index = buffer.startIndex
        while index < buffer.endIndex {
            let char = buffer[index]
            let next = buffer.index(after: index)
            if char == "\n" {
                if buffer.distance(from: buffer.startIndex, to: index) >= 1 { return next }
            } else if ".!?।".contains(char), next < buffer.endIndex, buffer[next].isWhitespace,
                buffer.distance(from: buffer.startIndex, to: next) >= minimum
            {
                return next
            }
            index = next
        }
        return nil
    }
}

/// "Hey Ira" comes later. A detector gets the same 20 ms frames of 16 kHz audio
/// as the voice detector and says when it heard the wake phrase; the app then
/// listens as if the mic button had been pressed. None ships in this version.
public protocol WakeWordDetector: AnyObject {
    func heard(_ samples: [Float]) -> Bool
}

/// The wake phrase in a live transcript ("Hey Ira" by default; each person may
/// choose their own on their Ira page).
public enum WakePhrase {
    /// Lower-case letters and single spaces only.
    static func normalized(_ text: String) -> String {
        text.lowercased().replacingOccurrences(of: "[^\\p{L} ]", with: " ", options: .regularExpression)
            .split(separator: " ").joined(separator: " ")
    }

    /// Whether `transcript` holds `phrase`, allowing the spellings a recogniser
    /// writes for "Ira" ("eera", "irah", "era").
    public static func heard(_ transcript: String, phrase: String = "Hey Ira") -> Bool {
        let text = " " + normalized(transcript) + " "
        let wanted = normalized(phrase)
        guard !wanted.isEmpty else { return false }
        var forms = [wanted]
        for spelling in ["eera", "irah", "era", "ira"] where wanted.contains("ira") {
            forms.append(wanted.replacingOccurrences(of: "ira", with: spelling))
        }
        if wanted.hasPrefix("hey ") {
            let rest = String(wanted.dropFirst(4))
            forms += ["hi " + rest, "hay " + rest].flatMap { form in
                [form] + ["eera", "irah", "era"].map { form.replacingOccurrences(of: "ira", with: $0) }
            }
        }
        return forms.contains { text.contains(" " + $0 + " ") }
    }
}
