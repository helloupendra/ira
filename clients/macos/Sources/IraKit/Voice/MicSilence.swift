import Foundation

/// Notices a microphone that gives Ira nothing.
///
/// A live microphone always picks up something: breath, a fan, the hum of the room. One that
/// macOS has silenced (a permission that no longer holds after a rebuild, or a muted or wrong
/// input) delivers zeros, or no frames at all. So when listening has run `afterMs` (3 s) and no
/// frame rose above `floor`, the input is silent, and `check` says so once per listen. A frame
/// above the floor later clears it, as when the person picks another input.
public struct MicSilence: Sendable {
    /// About -100 dBFS: below any real room, above the zeros of a silenced input.
    public static let floor: Float = 0.00001

    public let afterMs: Double
    public let floor: Float
    /// The input stayed silent past `afterMs`; false again once a frame rises above the floor.
    public private(set) var silent = false
    private var startedAt: Double?
    private var heard = false
    private var told = false

    public init(afterMs: Double = 3000, floor: Float = MicSilence.floor) {
        self.afterMs = afterMs
        self.floor = floor
    }

    /// Listening started at this time (ms, the caller's clock).
    public mutating func start(at time: Double) {
        startedAt = time
        heard = false
        silent = false
        told = false
    }

    /// Listening stopped: nothing to watch until the next start.
    public mutating func reset() {
        startedAt = nil
        heard = false
        silent = false
        told = false
    }

    /// One frame of input.
    public mutating func feed(_ samples: [Float]) {
        guard startedAt != nil, EnergyVAD.rms(samples) > floor else { return }
        heard = true
        silent = false
    }

    /// True once per listen: the moment the input has been silent for `afterMs`. Call it on
    /// each frame and on a timer, since a silenced input may send no frames at all.
    public mutating func check(at time: Double) -> Bool {
        guard let startedAt, !heard, !told, time - startedAt >= afterMs else { return false }
        told = true
        silent = true
        return true
    }
}
