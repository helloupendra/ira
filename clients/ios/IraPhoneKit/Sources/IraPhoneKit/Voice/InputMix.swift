import Foundation

/// Several microphone channels as one. The iPhone's voice processing can give more than one
/// channel, the voice in only some of them; averaging every channel that carries sound keeps
/// the voice, where a converter's own downmix may keep the first channel only.
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
}

/// The first second of each listen, per channel: what the microphone really gives, for the
/// log ("listening: echo cancellation on, input 48000 Hz × 1 ch; first second: 0.0123").
public final class InputProbe: @unchecked Sendable {
    private let lock = NSLock()
    private let wanted: Int
    private var squares: [Double] = []
    private var frames = 0
    private var told = false

    public init(seconds: Double, sampleRate: Double) {
        wanted = max(1, Int(seconds * sampleRate))
    }

    /// The report line: the input, then its first second's level per channel, "silent" when
    /// every channel gave pure zeros.
    public static func describe(setup: String, levels: [Float]) -> String {
        let shown = levels.map { String(format: "%.4f", $0) }.joined(separator: ", ")
        let silent = levels.allSatisfy { $0 <= MicWatch.floor }
        return "\(setup): \(silent ? "silent" : "sound") (\(shown))"
    }

    /// One buffer's channels; each channel's level once the first second has been heard, else nil.
    public func add(_ channels: [[Float]]) -> [Float]? {
        lock.lock()
        defer { lock.unlock() }
        guard !told, let length = channels.first?.count, length > 0 else { return nil }
        if squares.count != channels.count { squares = Array(repeating: 0, count: channels.count) }
        for (index, channel) in channels.enumerated() {
            squares[index] += channel.reduce(0) { $0 + Double($1) * Double($1) }
        }
        frames += length
        guard frames >= wanted else { return nil }
        told = true
        return squares.map { Float(($0 / Double(frames)).squareRoot()) }
    }
}
