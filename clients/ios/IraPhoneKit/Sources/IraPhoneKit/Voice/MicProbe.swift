import AVFoundation
import Foundation

/// "Test the microphone" in Settings: the same microphone tried a few ways, about two seconds
/// each, while the person talks. A call that heard only silence on one iPhone (no orange
/// microphone dot at all) needed telling apart: iOS refusing every way, or only the way calls
/// use it. Each step says what iOS answered and how loud the microphone was.
public struct MicProbeStep: Equatable, Sendable {
    public let name: String
    /// The loudest sample and the level (RMS), 0 to 1; nil when the step could not start.
    public let peak: Float?
    public let level: Float?
    /// How many buffers came in (zero: the input never ran).
    public let buffers: Int
    /// What else iOS said: an error, the route, a muted input.
    public let note: String

    public init(name: String, peak: Float?, level: Float?, buffers: Int, note: String) {
        self.name = name
        self.peak = peak
        self.level = level
        self.buffers = buffers
        self.note = note
    }

    /// Sound, silence (zeros) or nothing at all, as a word.
    public var verdict: String {
        guard let peak else { return "did not start" }
        if buffers == 0 { return "no audio" }
        return peak > 0.000_01 ? "sound" : "silence"
    }

    /// One line for the screen and the log.
    public var line: String {
        let numbers = peak.map { String(format: "peak %.4f, level %.4f, %d buffers", $0, level ?? 0, buffers) } ?? ""
        return [name + ": " + verdict, numbers, note].filter { !$0.isEmpty }.joined(separator: "; ")
    }
}

#if os(iOS)
@MainActor
public enum MicProbe {
    /// Run every step in turn; `progress` hears each one's name as it starts.
    public static func run(seconds: Double = 2, progress: @escaping (String) -> Void = { _ in }) async -> [MicProbeStep] {
        var steps: [MicProbeStep] = []
        progress("A recording, the plain way")
        steps.append(await recorder(seconds: seconds))
        let ways: [(String, AVAudioSession.Category, AVAudioSession.Mode, Bool)] = [
            ("Engine, record", .record, .default, false),
            ("Engine, play and record", .playAndRecord, .default, false),
            ("Engine, voice chat", .playAndRecord, .voiceChat, false),
            ("Engine, voice chat with voice processing (as calls)", .playAndRecord, .voiceChat, true),
        ]
        for (name, category, mode, processing) in ways {
            progress(name)
            steps.append(await engine(name, category: category, mode: mode, voiceProcessing: processing, seconds: seconds))
        }
        try? AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
        for step in steps { IraLog.shared.info("microphone test: \(step.line)") }
        return steps
    }

    /// What iOS says about the session now: the input it routes, and whether Ira's input is muted.
    static func describeSession() -> String {
        let session = AVAudioSession.sharedInstance()
        let inputs = session.currentRoute.inputs.map(\.portType.rawValue).joined(separator: "+")
        let muted = AVAudioApplication.shared.isInputMuted ? ", input muted" : ""
        let available = session.isInputAvailable ? "" : ", no input available"
        return "route \(inputs.isEmpty ? "none" : inputs)\(muted)\(available)"
    }

    static func configure(_ category: AVAudioSession.Category, _ mode: AVAudioSession.Mode) -> String? {
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(category, mode: mode, options: category == .playAndRecord ? [.defaultToSpeaker] : [])
            try session.setActive(true)
            if AVAudioApplication.shared.isInputMuted { try? AVAudioApplication.shared.setInputMuted(false) }
            return nil
        } catch {
            return "the session refused: \(error.localizedDescription)"
        }
    }

    static func engine(
        _ name: String, category: AVAudioSession.Category, mode: AVAudioSession.Mode, voiceProcessing: Bool, seconds: Double
    ) async -> MicProbeStep {
        if let problem = configure(category, mode) {
            return MicProbeStep(name: name, peak: nil, level: nil, buffers: 0, note: problem)
        }
        let engine = AVAudioEngine()
        let input = engine.inputNode
        var note = ""
        if voiceProcessing {
            do { try input.setVoiceProcessingEnabled(true) } catch { note = "voice processing refused: \(error.localizedDescription); " }
        }
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            return MicProbeStep(name: name, peak: nil, level: nil, buffers: 0, note: note + "no input format; " + describeSession())
        }
        let meter = Meter()
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in meter.add(buffer) }
        do {
            engine.prepare()
            try engine.start()
        } catch {
            input.removeTap(onBus: 0)
            return MicProbeStep(name: name, peak: nil, level: nil, buffers: 0, note: note + "the engine refused: \(error.localizedDescription)")
        }
        try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
        let session = describeSession()
        input.removeTap(onBus: 0)
        engine.stop()
        let (peak, level, buffers) = meter.result()
        return MicProbeStep(
            name: name, peak: peak, level: level, buffers: buffers,
            note: note + "\(Int(format.sampleRate)) Hz × \(format.channelCount) ch; " + session)
    }

    /// The control: AVAudioRecorder to a file that is deleted at once, with its own meter.
    static func recorder(seconds: Double) async -> MicProbeStep {
        let name = "Recorder"
        if let problem = configure(.record, .default) {
            return MicProbeStep(name: name, peak: nil, level: nil, buffers: 0, note: problem)
        }
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("ira-mic-test-\(UUID().uuidString).caf")
        defer { try? FileManager.default.removeItem(at: url) }
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: 16_000, AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16, AVLinearPCMIsFloatKey: false,
        ]
        do {
            let recorder = try AVAudioRecorder(url: url, settings: settings)
            recorder.isMeteringEnabled = true
            guard recorder.record() else {
                return MicProbeStep(name: name, peak: nil, level: nil, buffers: 0, note: "recording did not start; " + describeSession())
            }
            var loudest: Float = -160
            let end = Date().addingTimeInterval(seconds)
            while Date() < end {
                try? await Task.sleep(nanoseconds: 100_000_000)
                recorder.updateMeters()
                loudest = max(loudest, recorder.peakPower(forChannel: 0))
            }
            let session = describeSession()
            recorder.stop()
            // The meter is in dB: back to 0 to 1, so it reads like the others.
            let peak = loudest <= -159 ? 0 : Float(pow(10, Double(loudest) / 20))
            return MicProbeStep(name: name, peak: peak, level: nil, buffers: 1, note: String(format: "peak %.0f dB; ", loudest) + session)
        } catch {
            return MicProbeStep(name: name, peak: nil, level: nil, buffers: 0, note: "the recorder refused: \(error.localizedDescription)")
        }
    }
}

/// The loudest sample, the level and the buffer count, gathered on the audio thread.
final class Meter: @unchecked Sendable {
    private let lock = NSLock()
    private var peak: Float = 0
    private var squares: Double = 0
    private var samples = 0
    private var buffers = 0

    func add(_ buffer: AVAudioPCMBuffer) {
        let channels = Resampler.channels(buffer)
        lock.lock()
        defer { lock.unlock() }
        buffers += 1
        for channel in channels {
            for sample in channel {
                peak = max(peak, abs(sample))
                squares += Double(sample) * Double(sample)
            }
            samples += channel.count
        }
    }

    func result() -> (Float, Float, Int) {
        lock.lock()
        defer { lock.unlock() }
        let level = samples > 0 ? Float((squares / Double(samples)).squareRoot()) : 0
        return (peak, level, buffers)
    }
}
#endif
