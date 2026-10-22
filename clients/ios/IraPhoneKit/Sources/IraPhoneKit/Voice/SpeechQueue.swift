import Foundation

/// The order Ira's spoken sentences play in: by turn, then by `seq`, each once.
///
/// A sentence that arrives early waits for the ones before it. A barge-in or
/// Stop drops everything queued for that turn and before, and anything that
/// still arrives for them, so the iPhone never talks over the person.
public struct SpeechQueue<Item: Sendable>: Sendable {
    public struct Entry: Sendable {
        public let turn: Int
        public let seq: Int
        public let item: Item
    }

    private var waiting: [Entry] = []
    /// The next `seq` to play, per turn.
    private var nextSeq: [Int: Int] = [:]
    /// Turns at or below this one are never played again.
    public private(set) var stoppedThrough = 0

    public init() {}

    public var isEmpty: Bool { waiting.isEmpty }

    /// Add a sentence. Returns false when it belongs to a stopped turn and was dropped.
    @discardableResult
    public mutating func add(turn: Int, seq: Int, _ item: Item) -> Bool {
        guard turn > stoppedThrough else { return false }
        guard seq >= nextSeq[turn, default: 0] else { return false }  // already played
        guard !waiting.contains(where: { $0.turn == turn && $0.seq == seq }) else { return false }
        waiting.append(Entry(turn: turn, seq: seq, item: item))
        return true
    }

    /// The next sentence to play now, if the one before it has been played.
    public mutating func next() -> Entry? {
        // The oldest turn first: a newer turn waits until the older one is done or stopped.
        guard let turn = waiting.map(\.turn).min() else { return nil }
        let wanted = nextSeq[turn, default: 0]
        guard let index = waiting.firstIndex(where: { $0.turn == turn && $0.seq == wanted }) else {
            return nil
        }
        nextSeq[turn] = wanted + 1
        return waiting.remove(at: index)
    }

    /// A sentence is missing (it could not be fetched): play on past it.
    public mutating func skip(turn: Int, seq: Int) {
        if nextSeq[turn, default: 0] == seq { nextSeq[turn] = seq + 1 }
    }

    /// Barge-in or Stop: drop `turn` and everything before it.
    public mutating func stop(through turn: Int) {
        stoppedThrough = max(stoppedThrough, turn)
        waiting.removeAll { $0.turn <= stoppedThrough }
    }
}
