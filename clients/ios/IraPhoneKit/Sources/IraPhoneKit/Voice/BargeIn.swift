import Foundation

/// Speech heard while Ira speaks is the person talking over her, or her own voice from the
/// speaker, which echo cancellation does not always take out (a loud speaker, a phone lying
/// flat). Stopping her for her own echo cut her answers short, and sent her own words back
/// to her as the person's. So it is checked first: her voice is turned down at once, and if
/// the sound stays loud for `checkMs` with her quieter, it is the person, and she stops; if it
/// fades with her voice, it was her echo, and she carries on as before.
public struct BargeIn: Sendable {
    public struct Config: Sendable, Equatable {
        /// How long the sound is watched with Ira turned down.
        public var checkMs: Double = 300
        /// The share of those frames that must stay loud for it to be the person.
        public var loudShare: Double = 0.6
        public init() {}
    }

    public enum Step: Equatable, Sendable {
        /// Turn Ira down while the sound is checked.
        case duck
        /// It is the person: stop Ira, and send their speech from `start`, with what was held.
        case confirm(start: Double, held: [EnergyVAD.Output])
        /// It was Ira's own voice: turn her up again, and forget it.
        case release
    }

    public let config: Config
    private var start: Double?
    private var since: Double = 0
    private var frames = 0
    private var loud = 0
    private var held: [EnergyVAD.Output] = []

    public init(config: Config = Config()) {
        self.config = config
    }

    /// A check is going on: the voice detector's outputs are held.
    public var checking: Bool { start != nil }

    /// One frame's voice-detector outputs while Ira speaks (or while a check goes on), and
    /// whether the frame was loud for the detector.
    public mutating func feed(_ outputs: [EnergyVAD.Output], loud isLoud: Bool, at: Double) -> [Step] {
        guard let begun = start else {
            guard let index = outputs.firstIndex(where: { if case .speechStart = $0 { return true } else { return false } }),
                case .speechStart(let at0) = outputs[index]
            else { return [] }
            start = at0
            since = at
            frames = 0
            loud = 0
            held = Array(outputs[index...])
            return [.duck]
        }
        held.append(contentsOf: outputs)
        frames += 1
        if isLoud { loud += 1 }
        if outputs.contains(where: { if case .speechEnd = $0 { return true } else { return false } }) {
            reset()  // over before it was checked: too short to be the person talking over her
            return [.release]
        }
        guard at - since >= config.checkMs else { return [] }
        let person = Double(loud) >= config.loudShare * Double(max(frames, 1))
        let kept = held
        reset()
        return person ? [.confirm(start: begun, held: kept)] : [.release]
    }

    public mutating func reset() {
        start = nil
        frames = 0
        loud = 0
        held = []
    }
}

/// What happened in a call, for "Last call" in Settings: Ira's sentences received, played
/// and cut, the times the person talked over her, the echoes of her own voice that were not
/// taken for the person, and the times the iPhone's audio had to start again.
public struct CallStats: Sendable, Equatable {
    public var received = 0
    public var played = 0
    public var cut = 0
    public var bargeIns = 0
    public var echoes = 0
    public var restarts = 0
    public var stalls = 0

    public init() {}

    public var line: String {
        var parts = ["\(received) sentences from Ira, \(played) played"]
        if cut > 0 { parts.append("\(cut) cut short") }
        parts.append("\(bargeIns) times you talked over her")
        if echoes > 0 { parts.append("\(echoes) echoes of her voice ignored") }
        if restarts > 0 { parts.append("the audio started again \(restarts)×") }
        if stalls > 0 { parts.append("\(stalls) sentences that never finished") }
        return parts.joined(separator: "; ")
    }
}
