import Foundation

/// `GET /v1/info`, as far as this app needs it.
public struct ServerInfo: Equatable, Sendable {
    /// The name the person gave their assistant.
    public let name: String
    public let version: String?
    /// The server's speech-to-text and voice, by name (nil: none).
    public let stt: String?
    public let tts: String?
    /// A live call works here: streaming speech-to-text, a voice, and the permissions.
    public let live: Bool
    /// The language the person speaks first: hi-IN for Hindi or Hinglish, else en-IN.
    public let micLanguage: String
    public let permissions: [String]

    public init(_ json: JSONValue) {
        name = json["name"]?.stringValue.flatMap { $0.isEmpty ? nil : $0 } ?? "Ira"
        version = json["version"]?.stringValue
        stt = json["stt"]?.stringValue
        tts = json["tts"]?.stringValue
        live = json["live"]?.boolValue ?? false
        micLanguage = json["mic_language"]?.stringValue ?? "en-IN"
        permissions = (json["permissions"]?.arrayValue ?? []).compactMap(\.stringValue)
    }

    public var canAsk: Bool { permissions.contains("ask") }
    /// The server can speak answers in the person's Ira voice.
    public var speaks: Bool { permissions.contains("voice") && tts != nil }
}

/// How the app talks to Ira this time, in words the person sees.
public enum TalkMode: Equatable, Sendable {
    /// `/v1/voice/live`: the server hears, and speaks sentence by sentence.
    case live
    /// The iPhone's own speech recognition, the answer over `/v1/ask/stream`,
    /// spoken by the server's voice or the iPhone's.
    case phone(serverVoice: Bool)

    public static func choose(_ info: ServerInfo) -> TalkMode {
        info.live ? .live : .phone(serverVoice: info.speaks)
    }

    public var explanation: String {
        switch self {
        case .live:
            return "Live call: your Ira hears you as you speak and answers aloud. Speak over Ira to interrupt."
        case .phone(let serverVoice):
            let voice = serverVoice ? "Ira's own voice" : "the iPhone's voice"
            return "Phone mode: your Ira has no live calls, so the iPhone recognises your speech and Ira answers in \(voice). Tap Stop to interrupt."
        }
    }
}

/// `POST /v1/ask`'s answer.
public struct Answer: Equatable, Sendable {
    public let text: String
    public let conversationID: String?
    public let messageID: Int?
    public let action: ActionCard?

    public init(_ json: JSONValue) {
        text = json["text"]?.stringValue ?? ""
        conversationID = json["conversation_id"]?.stringValue
        messageID = json["message_id"]?.intValue
        action = json["action"].flatMap { $0.isNull ? nil : ActionCard($0) }
    }
}

/// One event of `POST /v1/ask/stream`.
public enum AskEvent: Equatable, Sendable {
    case start(conversationID: String)
    case tool(id: String, name: String)
    case toolResult(id: String, name: String, ok: Bool)
    case action(ActionCard)
    case delta(String)
    case error(String)
    case done(text: String, conversationID: String?, messageID: Int?)
    /// A type this version does not know: ignored.
    case other(String)

    public init(_ json: JSONValue) {
        switch json["type"]?.stringValue ?? "" {
        case "start":
            self = .start(conversationID: json["conversation_id"]?.stringValue ?? "")
        case "tool":
            self = .tool(id: json["id"]?.stringValue ?? "", name: json["name"]?.stringValue ?? "")
        case "tool_result":
            self = .toolResult(
                id: json["id"]?.stringValue ?? "", name: json["name"]?.stringValue ?? "",
                ok: json["ok"]?.boolValue ?? false)
        case "action":
            self = json["action"].flatMap(ActionCard.init).map { .action($0) } ?? .other("action")
        case "delta":
            self = .delta(json["text"]?.stringValue ?? "")
        case "error":
            self = .error(json["message"]?.stringValue ?? "no model could answer")
        case "done":
            self = .done(
                text: json["text"]?.stringValue ?? "", conversationID: json["conversation_id"]?.stringValue,
                messageID: json["message_id"]?.intValue)
        case let type:
            self = .other(type)
        }
    }
}

/// A proposed action (`ActionView`): what Ira wants to do, and what it needs first.
public struct ActionCard: Equatable, Sendable, Identifiable {
    public let id: String
    public let tool: String
    public let summary: String
    public var status: String
    public let tier: Int
    public let expiresIn: Int?
    public let canApprove: Bool
    public let canConfirm: Bool

    public init?(_ json: JSONValue) {
        guard let id = json["id"]?.stringValue, !id.isEmpty else { return nil }
        self.id = id
        tool = json["tool"]?.stringValue ?? ""
        summary = json["summary"]?.stringValue ?? "Ira proposed an action."
        status = json["status"]?.stringValue ?? "pending"
        tier = json["tier"]?.intValue ?? 3
        expiresIn = json["expires_in"]?.intValue
        canApprove = json["can_approve"]?.boolValue ?? false
        canConfirm = json["can_confirm"]?.boolValue ?? false
    }

    public init(id: String, tool: String, summary: String, status: String = "pending", tier: Int,
                expiresIn: Int? = 120, canApprove: Bool, canConfirm: Bool) {
        self.id = id
        self.tool = tool
        self.summary = summary
        self.status = status
        self.tier = tier
        self.expiresIn = expiresIn
        self.canApprove = canApprove
        self.canConfirm = canConfirm
    }

    /// What the card asks of the person.
    public enum Need: Equatable, Sendable {
        /// Tier 2: Yes or No (or say "haan" / "nahi").
        case yes
        /// Tier 3: the PIN, typed in the app, never spoken.
        case pin
        /// Their role may not confirm it, or someone else asked.
        case cannot(String)
        /// It is no longer waiting.
        case settled
    }

    public var need: Need {
        guard status == "pending" else { return .settled }
        if tier <= 2 {
            return canApprove ? .yes : .cannot("Only the person who asked can say yes to this.")
        }
        return canConfirm ? .pin : .cannot("Your role cannot confirm this. Ask the person who runs your Ira.")
    }

    /// The status, in words for the card.
    public var statusWords: String {
        switch status {
        case "pending": return need == .pin ? "Waiting for your PIN" : "Waiting for your yes"
        case "executing": return "Doing it…"
        case "executed": return "Done"
        case "failed": return "It failed"
        case "cancelled": return "Cancelled"
        case "expired": return "Expired: ask Ira again"
        default: return status
        }
    }
}

/// What came of approving, cancelling or confirming an action.
public struct ActionOutcome: Equatable, Sendable {
    public let status: String
    public let message: String?
    public let attemptsLeft: Int?
    public let lockedSeconds: Int?

    public init(_ json: JSONValue) {
        status = json["status"]?.stringValue ?? ""
        message = json["message"]?.stringValue
        attemptsLeft = json["attempts_left"]?.intValue
        lockedSeconds = json["locked_seconds"]?.intValue
    }

    public init(status: String, message: String? = nil, attemptsLeft: Int? = nil, lockedSeconds: Int? = nil) {
        self.status = status
        self.message = message
        self.attemptsLeft = attemptsLeft
        self.lockedSeconds = lockedSeconds
    }

    /// The new status for the card; a wrong PIN leaves it waiting.
    public var cardStatus: String? {
        switch status {
        case "executed", "failed", "cancelled", "expired": return status
        case "already_done": return "executed"
        default: return nil
        }
    }

    /// A sentence for the person, with what to do next.
    public var sentence: String {
        switch status {
        case "executed": return "Done."
        case "cancelled": return "Cancelled. Nothing was done."
        case "failed": return "It ran but failed: \(message ?? "no reason given"). Ask Ira again, or do it yourself."
        case "wrong_pin":
            let left = attemptsLeft.map { " \($0) \($0 == 1 ? "try" : "tries") left before actions lock." } ?? ""
            return "That PIN is not right.\(left)"
        case "locked":
            let minutes = lockedSeconds.map { max(1, Int((Double($0) / 60).rounded(.up))) }
            return "Too many wrong PINs: actions are locked" + (minutes.map { " for \($0) more minute\($0 == 1 ? "" : "s")." } ?? " for a while.")
        case "expired": return "This proposal expired (after 2 minutes). Ask Ira again."
        case "no_pin": return "You have no action PIN yet. Set one in the Ira web app's menu, then ask again."
        case "not_allowed": return "Your role may not confirm this action."
        case "needs_pin": return "This needs your PIN, not a yes."
        case "already_done": return "This was already answered."
        case "not_found": return "Your Ira no longer has this proposal. Ask again."
        default: return message ?? "Your Ira answered: \(status)."
        }
    }
}

/// Why an answer is reported (`ReportIn.reason`).
public enum ReportReason: String, CaseIterable, Sendable, Identifiable {
    case wrong, harmful, offensive, `private`, other

    public var id: String { rawValue }

    public var words: String {
        switch self {
        case .wrong: return "It is wrong"
        case .harmful: return "It is harmful or dangerous"
        case .offensive: return "It is offensive"
        case .private: return "It shows something private"
        case .other: return "Something else"
        }
    }
}
