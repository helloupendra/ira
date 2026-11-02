import Foundation

/// A simple energy voice detector, run on the Mac on 20 ms frames of 16 kHz audio.
///
/// * Speech starts when the level stays above the threshold for `startMs`
///   (60 ms), so a click or a cough does not count.
/// * When it starts, the last `leadInMs` (about 300 ms) before it are sent
///   too, so the first syllable is not cut.
/// * Speech ends after `hangoverMs` (about 600 ms) of quiet; the end is
///   stamped at the last loud frame's end, not when the hangover ran out.
/// * The threshold follows the room: it is at least `threshold`, and at least
///   `noiseFactor` times the quiet level heard so far, so a fan does not
///   count as speech.
/// * While Ira is speaking (`replying`), the threshold is raised and speech
///   must last longer before it counts, so Ira's own voice from the speakers
///   rarely interrupts her; the person's voice does (barge-in).
/// * Without the Mac's echo cancellation (`withoutEchoCancellation`), Ira would
///   hear herself, so nothing counts as speech while she speaks and for a moment
///   after (`halfDuplex`); a turn needs a quarter of a second of voice, with
///   short dips allowed (`gapMs`), and ends after 900 ms of quiet, so a slow or
///   quiet speaker is not cut into one-word turns.
public struct EnergyVAD: Sendable {
    public struct Config: Sendable, Equatable {
        public var sampleRate: Double = 16_000
        public var frameMs: Double = 20
        public var threshold: Float = 0.02
        public var startMs: Double = 160
        public var hangoverMs: Double = 900
        public var leadInMs: Double = 300
        public var maxSpeechMs: Double = 60_000
        public var noiseFactor: Float = 3
        public var replyFactor: Float = 2.5
        public var replyStartMs: Double = 200
        /// Quiet within the start of speech that does not break it: dips between syllables.
        public var gapMs: Double = 80
        /// Nothing counts as speech while Ira speaks, nor for `echoTailMs` after.
        public var halfDuplex = false
        public var echoTailMs: Double = 400
        /// How fast the room's quiet level follows a quieter frame, and a louder one.
        public var floorFall: Float = 0.05
        public var floorRise: Float = 0.05
        public init() {}

        /// For a microphone without the Mac's echo cancellation: Ira's voice from the
        /// speakers reaches it, and nothing evens out a quiet voice.
        public static var withoutEchoCancellation: Config {
            var config = Config()
            config.hangoverMs = 900
            config.startMs = 250
            config.gapMs = 80
            config.halfDuplex = true
            // A quiet voice under the threshold is not the room: the room's level rises only
            // slowly (over about 4 s), or the threshold would climb away from the voice.
            config.floorFall = 0.2
            config.floorRise = 0.005
            return config
        }
    }

    public enum Output: Equatable, Sendable {
        /// Speech began at this time (ms, the caller's clock).
        case speechStart(at: Double)
        /// Audio to send: 16-bit little-endian mono PCM.
        case audio(Data)
        /// Speech ended at this time: the end of the last loud frame.
        case speechEnd(at: Double)
    }

    public let config: Config
    public var replying = false
    public private(set) var speaking = false
    public private(set) var noiseFloor: Float = 0
    public private(set) var level: Float = 0

    private var recent: [(at: Double, pcm: Data, loud: Bool)] = []
    private var loudRun = 0
    private var quietRun = 0
    private var lastReplyEnd = -Double.infinity
    private var runStart: Double = 0
    private var lastLoudEnd: Double = 0
    private var speechStarted: Double = 0

    public init(config: Config = Config()) {
        self.config = config
    }

    public var effectiveThreshold: Float {
        // The room can raise the threshold, but never past a level normal speech reaches.
        let base = max(config.threshold, min(noiseFloor * config.noiseFactor, 0.12))
        return replying ? base * config.replyFactor : base
    }

    /// The level of a frame: its root mean square, 0 to 1.
    public static func rms(_ samples: [Float]) -> Float {
        guard !samples.isEmpty else { return 0 }
        var sum: Float = 0
        for sample in samples { sum += sample * sample }
        return (sum / Float(samples.count)).squareRoot()
    }

    /// Feed one frame that starts at `at` (ms); returns what to do now.
    public mutating func process(_ samples: [Float], at: Double) -> [Output] {
        let level = EnergyVAD.rms(samples)
        self.level = level
        let pcm = PCM.int16Data(samples)
        let end = at + Double(samples.count) / config.sampleRate * 1000
        if replying { lastReplyEnd = end }
        // Half-duplex: Ira's own voice (and its echo in the room) is never the person's turn.
        let deaf = config.halfDuplex && (replying || end - lastReplyEnd < config.echoTailMs)
        let loud = !deaf && level > effectiveThreshold
        var out: [Output] = []

        if !speaking {
            if !loud && !replying && !deaf {
                // Learn the room's quiet level, slowly, only from quiet frames.
                let weight = level < noiseFloor ? config.floorFall : config.floorRise
                noiseFloor = noiseFloor == 0 ? level : noiseFloor * (1 - weight) + level * weight
            }
            recent.append((at, pcm, loud))
            let keep = Int((config.leadInMs + max(config.startMs, config.replyStartMs)) / config.frameMs) + 1
            if recent.count > keep { recent.removeFirst(recent.count - keep) }
            if loud {
                if loudRun == 0 { runStart = at }
                loudRun += 1
                quietRun = 0
                lastLoudEnd = end
            } else if loudRun > 0 {
                // A dip of up to gapMs between syllables keeps the run; a longer one ends it.
                quietRun += 1
                if deaf || Double(quietRun) * config.frameMs > config.gapMs {
                    loudRun = 0
                    quietRun = 0
                }
            }
            let needed = replying ? config.replyStartMs : config.startMs
            if loud, loudRun > 0, end - runStart >= needed {
                speaking = true
                speechStarted = runStart
                out.append(.speechStart(at: runStart))
                // The lead-in: up to leadInMs before the speech, then the speech so far.
                let from = runStart - config.leadInMs
                for frame in recent where frame.at >= from - 0.001 {
                    out.append(.audio(frame.pcm))
                }
                recent.removeAll()
                loudRun = 0
                quietRun = 0
            }
            return out
        }

        out.append(.audio(pcm))
        if loud { lastLoudEnd = end }
        if end - lastLoudEnd >= config.hangoverMs || end - speechStarted >= config.maxSpeechMs {
            speaking = false
            out.append(.speechEnd(at: lastLoudEnd))
        }
        return out
    }

    /// Forget any speech in progress (the person pressed stop).
    public mutating func reset() {
        speaking = false
        recent.removeAll()
        loudRun = 0
        quietRun = 0
    }
}

/// 16-bit PCM and WAV.
public enum PCM {
    public static func int16Data(_ samples: [Float]) -> Data {
        var data = Data(capacity: samples.count * 2)
        for sample in samples {
            let clipped = max(-1, min(1, sample))
            let value = Int16(clipped * Float(Int16.max))
            withUnsafeBytes(of: value.littleEndian) { data.append(contentsOf: $0) }
        }
        return data
    }

    /// A WAV file around 16-bit mono PCM.
    public static func wav(_ pcm: Data, sampleRate: Int = 16_000) -> Data {
        var data = Data()
        func append<T: FixedWidthInteger>(_ value: T) {
            withUnsafeBytes(of: value.littleEndian) { data.append(contentsOf: $0) }
        }
        data.append(contentsOf: Array("RIFF".utf8))
        append(UInt32(36 + pcm.count))
        data.append(contentsOf: Array("WAVEfmt ".utf8))
        append(UInt32(16))
        append(UInt16(1))  // PCM
        append(UInt16(1))  // mono
        append(UInt32(sampleRate))
        append(UInt32(sampleRate * 2))
        append(UInt16(2))
        append(UInt16(16))
        data.append(contentsOf: Array("data".utf8))
        append(UInt32(pcm.count))
        data.append(pcm)
        return data
    }
}
