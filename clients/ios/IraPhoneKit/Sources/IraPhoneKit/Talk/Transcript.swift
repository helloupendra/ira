import Foundation

/// One line of the conversation on screen: what the person said, what Ira
/// answered, or a note (a proposed action, a problem).
public struct Entry: Identifiable, Equatable, Sendable {
    public enum Role: Equatable, Sendable { case you, ira, note }

    public let id: UUID
    public let role: Role
    public var text: String
    /// Which talk it belongs to (each live call numbers its turns from 1) and its turn.
    public var source: Int
    public var turn: Int?
    /// Ira's stored answer, for Report.
    public var messageID: Int?
    public var action: ActionCard?
    public var reported = false
    /// Still being written.
    public var streaming = false

    public init(role: Role, text: String, source: Int = 0, turn: Int? = nil, action: ActionCard? = nil) {
        self.id = UUID()
        self.role = role
        self.text = text
        self.source = source
        self.turn = turn
        self.action = action
    }

    /// Report is offered on Ira's finished answers that the server stored.
    public var canReport: Bool { role == .ira && !streaming && messageID != nil && !reported }
}

/// The conversation's lines, and how each thing Ira says back changes them.
public struct Transcript: Sendable {
    public private(set) var entries: [Entry] = []
    /// A typed line waiting for its turn number, so a "heard" for it is not shown twice.
    private var typed: UUID?

    public init() {}

    /// The person typed (or the phone heard) this; returns its line's id.
    @discardableResult
    public mutating func said(_ text: String, source: Int, turn: Int? = nil) -> UUID {
        let entry = Entry(role: .you, text: text, source: source, turn: turn)
        entries.append(entry)
        typed = turn == nil ? entry.id : nil
        return entry.id
    }

    public mutating func note(_ text: String, source: Int = 0) {
        entries.append(Entry(role: .note, text: text, source: source))
    }

    func answerIndex(source: Int, turn: Int) -> Int? {
        entries.lastIndex { $0.role == .ira && $0.source == source && $0.turn == turn }
    }

    /// Apply one event from the talk numbered `source`.
    public mutating func apply(_ event: TalkEvent, source: Int) {
        switch event {
        case .heard(let turn, let text):
            if let typed, let index = entries.firstIndex(where: { $0.id == typed }),
                entries[index].text.trimmingCharacters(in: .whitespaces) == text.trimmingCharacters(in: .whitespaces)
            {
                entries[index].turn = turn
                entries[index].source = source
            } else {
                entries.append(Entry(role: .you, text: text, source: source, turn: turn))
            }
            typed = nil
        case .delta(let turn, let text):
            if let index = answerIndex(source: source, turn: turn) {
                entries[index].text += text
            } else {
                var entry = Entry(role: .ira, text: text, source: source, turn: turn)
                entry.streaming = true
                entries.append(entry)
            }
        case .action(let turn, let card):
            if let index = entries.firstIndex(where: { $0.action?.id == card.id }) {
                entries[index].action = card
            } else {
                entries.append(Entry(role: .note, text: card.summary, source: source, turn: turn, action: card))
            }
        case .done(let turn, let text, let messageID):
            if let index = answerIndex(source: source, turn: turn) {
                if !text.isEmpty { entries[index].text = text }
                entries[index].messageID = messageID
                entries[index].streaming = false
            } else if !text.isEmpty {
                var entry = Entry(role: .ira, text: text, source: source, turn: turn)
                entry.messageID = messageID
                entries.append(entry)
            }
        case .interrupted(let turn):
            if let index = answerIndex(source: source, turn: turn) { entries[index].streaming = false }
        case .error(let message, _):
            for index in entries.indices where entries[index].streaming && entries[index].source == source {
                entries[index].streaming = false
            }
            note(Plain.sentence(message), source: source)
        case .ready, .partial, .tool, .audio, .say, .closed:
            break
        }
    }

    /// A proposal was answered: its card shows the new status.
    public mutating func settle(actionID: String, status: String) {
        for index in entries.indices where entries[index].action?.id == actionID {
            entries[index].action?.status = status
        }
    }

    public mutating func markReported(_ id: UUID) {
        if let index = entries.firstIndex(where: { $0.id == id }) { entries[index].reported = true }
    }

    public mutating func clear() {
        entries.removeAll()
        typed = nil
    }
}
