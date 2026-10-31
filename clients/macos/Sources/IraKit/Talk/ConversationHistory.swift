import Foundation

/// One of the person's recent conversations (`GET /v1/conversations`), for the window's list.
public struct ConversationSummary: Equatable, Sendable, Identifiable {
    public let id: String
    public let startedAt: Date
    public let lastAt: Date
    public let turns: Int
    public let preview: String?

    public init(id: String, startedAt: Date, lastAt: Date, turns: Int, preview: String?) {
        self.id = id
        self.startedAt = startedAt
        self.lastAt = lastAt
        self.turns = turns
        self.preview = preview
    }

    public init?(_ json: JSONValue) {
        guard let id = json["id"]?.stringValue, let started = json["started_at"]?.doubleValue,
            let last = json["last_at"]?.doubleValue
        else { return nil }
        let preview = json["preview"]?.stringValue?.trimmingCharacters(in: .whitespacesAndNewlines)
        self.init(
            id: id, startedAt: Date(timeIntervalSince1970: started), lastAt: Date(timeIntervalSince1970: last),
            turns: json["turns"]?.intValue ?? 0, preview: preview?.isEmpty == false ? preview : nil)
    }

    /// The first thing the person said, else when it started.
    public var title: String {
        preview ?? "Conversation at \(startedAt.formatted(date: .omitted, time: .shortened))"
    }
}

/// A line of a stored conversation: what the person said, Ira's answer, or a note about an action.
public struct ConversationLine: Equatable, Sendable {
    public enum Kind: Equatable, Sendable { case person, ira, note }
    public let kind: Kind
    public let text: String

    public init(_ kind: Kind, _ text: String) {
        self.kind = kind
        self.text = text
    }
}

public enum ConversationHistory {
    /// Today's conversations, the latest active first.
    public static func today(_ rows: [ConversationSummary], now: Date = Date(), calendar: Calendar = .current) -> [ConversationSummary] {
        let start = calendar.startOfDay(for: now)
        return rows.filter { $0.lastAt >= start }.sorted { $0.lastAt > $1.lastAt }
    }

    /// A transcript (`GET /v1/conversations/{id}`) as the window shows it, as the web app does:
    /// the person's words, Ira's answers and a note for each action, never tool calls or results.
    public static func lines(_ messages: JSONValue) -> [ConversationLine] {
        var lines: [ConversationLine] = []
        for message in messages.arrayValue ?? [] {
            let text = message["content"]?.stringValue?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            switch message["role"]?.stringValue {
            case "user" where !text.isEmpty: lines.append(ConversationLine(.person, text))
            case "assistant" where !text.isEmpty: lines.append(ConversationLine(.ira, text))
            default: break
            }
            if let action = message["action"], let summary = action["summary"]?.stringValue {
                lines.append(ConversationLine(.note, "\(status(action["status"]?.stringValue)): \(summary)"))
            }
        }
        return lines
    }

    static func status(_ status: String?) -> String {
        switch status {
        case "pending": return "Waiting for you"
        case "executed": return "Done"
        case "cancelled": return "Cancelled"
        case "expired": return "Expired"
        case "failed": return "Failed"
        case "rejected", "refused": return "Refused"
        default: return status ?? "An action"
        }
    }
}
