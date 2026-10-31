import Foundation

/// "How Ira got this", as small receipts under an answer: each tool it used and how long it
/// took, such as "files find · 0.4 s". A tool runs from its event until the turn's next one.
public struct Receipts: Sendable {
    private struct Use: Sendable {
        let name: String
        let start: Date
        var end: Date?
    }

    private var uses: [Int: [Use]] = [:]

    public init() {}

    /// Ira began using a tool in this turn (the one before it, if still open, has ended).
    public mutating func began(_ name: String, turn: Int, at: Date = Date()) {
        ended(turn: turn, at: at)
        uses[turn, default: []].append(Use(name: name, start: at))
    }

    /// Something else happened in the turn: a tool still open has ended.
    public mutating func ended(turn: Int, at: Date = Date()) {
        guard var list = uses[turn], let last = list.indices.last, list[last].end == nil else { return }
        list[last].end = at
        uses[turn] = list
    }

    /// The turn's receipts, once; the turn is forgotten after.
    public mutating func take(turn: Int, at: Date = Date()) -> [String] {
        ended(turn: turn, at: at)
        defer { uses[turn] = nil }
        return (uses[turn] ?? []).map { Receipts.line($0.name, seconds: ($0.end ?? at).timeIntervalSince($0.start)) }
    }

    /// "files find · 0.4 s"
    public static func line(_ tool: String, seconds: TimeInterval) -> String {
        let name = tool.replacingOccurrences(of: "_", with: " ")
        let time = seconds < 10 ? String(format: "%.1f s", max(seconds, 0)) : "\(Int(seconds.rounded())) s"
        return "\(name) · \(time)"
    }
}
