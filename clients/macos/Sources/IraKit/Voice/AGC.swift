import Foundation

/// A software automatic gain control for the microphone, for when the Mac's voice processing
/// (which has its own) is off: it steers speech toward `target` so the voice detector and the
/// transcriber get a proper level from a quiet voice or a low input volume.
///
/// * Only voice moves the gain: a frame above `gateFactor` times the room's quiet level (and
///   above `minSignal`). In between, the gain holds, so silence is never pumped up.
/// * Turning down is quick (`attackMs`), turning up gentle (`releaseMs`), and the gain stays
///   within `minGain`...`maxGain` (8×).
/// * The gain changes smoothly across each frame, and a soft limiter keeps peaks under 1.
public struct SoftwareAGC: Sendable {
    public struct Config: Sendable, Equatable {
        public var target: Float = 0.1
        public var minGain: Float = 0.5
        public var maxGain: Float = 8
        public var attackMs: Double = 60
        public var releaseMs: Double = 600
        public var gateFactor: Float = 2.5
        public var minSignal: Float = 0.0015
        public var frameMs: Double = 20
        public init() {}
    }

    public let config: Config
    public private(set) var gain: Float = 1
    public private(set) var noiseFloor: Float = 0

    public init(config: Config = Config()) {
        self.config = config
    }

    /// Whether a frame at this level is voice, for the gain.
    func voiced(_ level: Float) -> Bool {
        level > max(config.minSignal, noiseFloor * config.gateFactor)
    }

    /// One frame, at the gain it calls for. With `adapt` false (Ira is speaking, and her voice
    /// from the speakers is not the person's), the gain holds.
    public mutating func process(_ samples: [Float], adapt: Bool = true) -> [Float] {
        guard !samples.isEmpty else { return samples }
        let level = EnergyVAD.rms(samples)
        var next = gain
        let voice = voiced(level)
        if adapt {
            // The room's quiet level, learnt from quiet frames; under sound it creeps up over
            // ten seconds or so, so a voice from the very first frame is not taken for the room.
            if !voice || level < noiseFloor {
                noiseFloor = noiseFloor == 0 ? level : min(level, noiseFloor * 0.9 + level * 0.1)
            } else {
                noiseFloor = noiseFloor * 0.998 + level * 0.002
            }
        }
        if adapt, voice {
            let wanted = min(max(config.target / level, config.minGain), config.maxGain)
            let time = wanted < gain ? config.attackMs : config.releaseMs
            let step = Float(1 - exp(-config.frameMs / time))
            next = exp(log(gain) + step * (log(wanted) - log(gain)))
        }
        var out = samples
        let count = Float(samples.count)
        for index in out.indices {
            let applied = gain + (next - gain) * Float(index + 1) / count
            out[index] = SoftwareAGC.limit(samples[index] * applied)
        }
        gain = next
        return out
    }

    /// A soft limiter: untouched up to 0.9, then bent smoothly to just under 1.
    static func limit(_ sample: Float) -> Float {
        let size = abs(sample)
        guard size > 0.9 else { return sample }
        let bent = 0.9 + 0.099 * tanh((size - 0.9) / 0.1)
        return sample < 0 ? -bent : bent
    }

    /// Start again (another input, or voice processing switched on or off).
    public mutating func reset() {
        gain = 1
        noiseFloor = 0
    }
}

/// One input frame from a microphone that gives several channels (voice processing does on
/// some Macs, with the voice in one of them): the channels that carry anything, averaged.
/// Taking channel 0 alone gave pure zeros when the voice was elsewhere.
public enum Downmix {
    /// Below this a channel is empty, not quiet.
    public static let empty: Float = 0.000_001

    public static func average(_ channels: [[Float]]) -> [Float] {
        guard let length = channels.map(\.count).max(), length > 0 else { return [] }
        let live = channels.filter { $0.count == length && EnergyVAD.rms($0) > empty }
        guard !live.isEmpty else { return [Float](repeating: 0, count: length) }
        if live.count == 1 { return live[0] }
        var out = [Float](repeating: 0, count: length)
        for channel in live {
            for index in 0..<length { out[index] += channel[index] }
        }
        let share = 1 / Float(live.count)
        return out.map { $0 * share }
    }

    /// Each channel's level, for the log: what the input really gives.
    public static func levels(_ channels: [[Float]]) -> [Float] {
        channels.map { EnergyVAD.rms($0) }
    }
}
