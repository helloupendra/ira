import Foundation

/// What a call shows, in one word the person can trust at a glance.
public enum CallPhase: Equatable, Sendable {
    case connecting
    /// The microphone is on and Ira waits for the person.
    case listening
    /// The person is speaking, and Ira hears it.
    case hearing
    /// The turn is over and Ira works on the answer.
    case thinking
    /// Ira is talking; talking over her stops her.
    case speaking
    /// The microphone gives Ira nothing at all: no sound, or no audio.
    case micSilent

    /// The phase for a call's state. Ira speaking shows first (it is what the person
    /// hears), then the person speaking, then the answer on its way; a microphone that
    /// gives nothing shows only while nothing else is going on.
    public static func of(connecting: Bool, hearing: Bool, speaking: Bool, thinking: Bool, micSilent: Bool) -> CallPhase {
        if connecting { return .connecting }
        if speaking { return .speaking }
        if hearing { return .hearing }
        if thinking { return .thinking }
        if micSilent { return .micSilent }
        return .listening
    }

    public var title: String {
        switch self {
        case .connecting: return "Connecting…"
        case .listening: return "Listening"
        case .hearing: return "Hearing you"
        case .thinking: return "Thinking"
        case .speaking: return "Speaking"
        case .micSilent: return "Ira hears nothing"
        }
    }

    public var detail: String {
        switch self {
        case .connecting: return "Getting your Ira on the line"
        case .listening: return "Talk any time, in any language"
        case .hearing: return "Keep going; Ira answers when you pause"
        case .thinking: return "Working on your answer"
        case .speaking: return "Talk over Ira to stop her"
        case .micSilent:
            return "The microphone is giving only silence. Check Settings, Ira, Microphone is on, and that no other app is recording, then tap Try again."
        }
    }
}

/// The last few voice levels, oldest first, for the call's waveform.
public struct LevelHistory: Sendable, Equatable {
    public let count: Int
    public private(set) var levels: [Float]

    public init(count: Int = 32) {
        self.count = count
        self.levels = Array(repeating: 0, count: count)
    }

    public mutating func add(_ level: Float) {
        levels.removeFirst()
        levels.append(max(0, level))
    }

    public mutating func clear() {
        levels = Array(repeating: 0, count: count)
    }
}

/// Watches a call's microphone. When nothing above `floor` arrived for `afterMs`
/// (from the start, or since the last sound), the input is silent: a microphone
/// that gives pure zeros, or audio that never arrives at all. A real room is never
/// that quiet, so a quiet person does not count. One sound clears it.
public struct MicWatch: Sendable {
    public static let floor: Float = 0.00001
    public let afterMs: Double
    public let floor: Float
    private var startedAt: Double?
    private var heardAt: Double?
    public private(set) var silent = false

    public init(afterMs: Double = 3000, floor: Float = MicWatch.floor) {
        self.afterMs = afterMs
        self.floor = floor
    }

    public mutating func start(at: Double) {
        startedAt = at
        heardAt = nil
        silent = false
    }

    public mutating func stop() {
        startedAt = nil
        heardAt = nil
        silent = false
    }

    /// A frame's level arrived at `at`.
    public mutating func frame(level: Float, at: Double) {
        guard startedAt != nil, level > floor else { return }
        heardAt = at
        silent = false
    }

    /// Looked at on a timer too, since audio that never arrives sends no frames.
    @discardableResult
    public mutating func check(now: Double) -> Bool {
        guard let startedAt else { return false }
        silent = now - (heardAt ?? startedAt) > afterMs
        return silent
    }
}
