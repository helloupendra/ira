import AVFoundation
import Foundation

/// The microphone and the speaker on one AVAudioEngine, for calls.
///
/// On the iPhone the audio session is `.playAndRecord` in `.voiceChat` mode,
/// on the speaker unless headphones are in, and the engine's voice processing
/// is on: the iPhone's echo canceller takes Ira's own voice out of what the
/// microphone hears, so only the person's voice interrupts her. Ira's MP3
/// sentences play through the same engine for that reason, one after another
/// in order; a barge-in stops them at once.
@MainActor
public final class AudioEngine: NSObject {
    /// 16 kHz mono frames of 20 ms, with their start time (ms, `monotonicMs`).
    public var onFrame: (([Float], Double) -> Void)?
    /// The first sound of a turn started playing.
    public var onTurnStarted: ((Int) -> Void)?
    /// Nothing is left to play.
    public var onIdle: (() -> Void)?
    /// iOS took the audio away (a phone call, Siri, an alarm): the call ends.
    public var onInterrupted: ((String) -> Void)?
    /// What the microphone gives, once a listen: its format, and its level over the first
    /// second ("48000 Hz × 1 ch, echo cancellation on: silent (0.0000)").
    public var onInputReport: ((String) -> Void)?

    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let synthesizer = AVSpeechSynthesizer()
    private let playFormat = AVAudioFormat(standardFormatWithSampleRate: 24_000, channels: 1)!
    private var chunker = FrameChunker()
    public private(set) var listening = false
    public private(set) var echoCancelling = false

    enum Sound: Sendable {
        case mp3(Data)
        case say(String)
    }

    private var queue = SpeechQueue<Sound>()
    private var busy = false
    private var startedTurns: Set<Int> = []
    private var generation = 0
    private var observers: [NSObjectProtocol] = []

    public var playing: Bool { busy || !queue.isEmpty }

    public override init() {
        super.init()
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: playFormat)
        synthesizer.delegate = self
    }

    // MARK: The audio session

    /// Ready the iPhone for a call: play and record, voice chat, the speaker by default.
    public func activateSession() throws {
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetoothHFP])
        try session.setPreferredIOBufferDuration(0.02)
        try session.setActive(true)
        if !observers.isEmpty { return }
        let center = NotificationCenter.default
        observers.append(center.addObserver(
            forName: AVAudioSession.interruptionNotification, object: session, queue: .main
        ) { [weak self] note in
            let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            let began = raw.flatMap { AVAudioSession.InterruptionType(rawValue: $0) } == .began
            guard began else { return }
            MainActor.assumeIsolated {
                self?.onInterrupted?("The call ended because the iPhone needed its audio (a phone call, Siri or an alarm). Tap Call to talk again.")
            }
        })
        observers.append(center.addObserver(
            forName: AVAudioSession.mediaServicesWereResetNotification, object: session, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated {
                self?.onInterrupted?("The iPhone restarted its audio. Tap Call to talk again.")
            }
        })
        #endif
    }

    /// Give the audio back to other apps when the call ends.
    public func deactivateSession() {
        #if os(iOS)
        for observer in observers { NotificationCenter.default.removeObserver(observer) }
        observers.removeAll()
        try? AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
        #endif
    }

    // MARK: Listening

    public func startListening() throws {
        guard !listening else { return }
        let muted = AudioEngine.unmuteInput()
        let input = engine.inputNode
        if !echoCancelling {
            do {
                try input.setVoiceProcessingEnabled(true)
                echoCancelling = true
            } catch {
                IraLog.shared.info("voice processing is not available here")
            }
        }
        if echoCancelling {
            // Voice processing's input can come up muted or bypassed: make sure it is neither,
            // and that its own gain control is on (it evens out a quiet voice).
            input.isVoiceProcessingInputMuted = false
            input.isVoiceProcessingBypassed = false
            input.isVoiceProcessingAGCEnabled = true
        }
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            throw ToolFailure("no microphone is available")
        }
        guard let resampler = Resampler(from: format) else {
            throw ToolFailure("the microphone's audio could not be converted")
        }
        let setup = "\(Int(format.sampleRate)) Hz × \(format.channelCount) ch, echo cancellation \(echoCancelling ? "on" : "off")"
            + (muted ? ", was muted" : "")
        IraLog.shared.info("listening: \(setup)")
        chunker = FrameChunker()
        input.removeTap(onBus: 0)
        let probe = InputProbe(seconds: 1, sampleRate: format.sampleRate)
        input.installTap(onBus: 0, bufferSize: 1024, format: format, block: AudioEngine.tap(
            resampler, probe: probe, setup: setup,
            report: { [weak self] line in self?.onInputReport?(line) }
        ) { [weak self] samples, end in
            self?.collect(samples, endingAt: end)
        })
        if !engine.isRunning {
            engine.prepare()
            try engine.start()
        }
        listening = true
    }

    /// iOS keeps an input mute for each app (voice chat apps, a mute in the system's call
    /// controls): while it is on, the microphone gives only zeros. Returns whether it was on.
    @discardableResult
    static func unmuteInput() -> Bool {
        #if os(iOS)
        let app = AVAudioApplication.shared
        guard app.isInputMuted else { return false }
        do {
            try app.setInputMuted(false)
            IraLog.shared.info("the app's microphone input was muted; it is on again")
        } catch {
            IraLog.shared.info("the app's microphone input is muted, and unmuting failed: \(error.localizedDescription)")
        }
        return true
        #else
        return false
        #endif
    }

    /// The tap runs on the audio thread: it mixes the channels and converts there, and hands
    /// the samples to the main actor. Made outside the actor, so it never claims to run on it.
    nonisolated static func tap(
        _ resampler: Resampler, probe: InputProbe, setup: String,
        report: @escaping @MainActor @Sendable (String) -> Void,
        deliver: @escaping @MainActor @Sendable ([Float], Double) -> Void
    ) -> AVAudioNodeTapBlock {
        { buffer, _ in
            let now = monotonicMs()
            let channels = Resampler.channels(buffer)
            if let levels = probe.add(channels) {
                let line = InputProbe.describe(setup: setup, levels: levels)
                IraLog.shared.info("listening: \(line)")
                Task { @MainActor in report(line) }
            }
            guard let samples = resampler.convert(buffer, channels: channels) else { return }
            Task { @MainActor in deliver(samples, now) }
        }
    }

    public func stopListening() {
        guard listening else { return }
        engine.inputNode.removeTap(onBus: 0)
        listening = false
        chunker = FrameChunker()
        if !playing { engine.pause() }
    }

    private func collect(_ samples: [Float], endingAt end: Double) {
        guard listening else { return }
        for (frame, at) in chunker.add(samples, endingAt: end) {
            onFrame?(frame, at)
        }
    }

    /// Stop everything: the call is over.
    public func shutDown() {
        stopListening()
        stopPlayback(through: Int.max - 1)
        engine.stop()
        deactivateSession()
    }

    // MARK: Speaking

    public func play(mp3: Data, turn: Int, seq: Int) {
        queue.add(turn: turn, seq: seq, .mp3(mp3))
        next()
    }

    public func say(_ text: String, turn: Int, seq: Int) {
        queue.add(turn: turn, seq: seq, .say(text))
        next()
    }

    /// Stop talking at once and forget what was queued for `turn` and before
    /// (barge-in or Stop).
    public func stopPlayback(through turn: Int) {
        generation += 1
        queue.stop(through: turn)
        player.stop()
        if synthesizer.isSpeaking { synthesizer.stopSpeaking(at: .immediate) }
        busy = false
    }

    private func next() {
        guard !busy else { return }
        guard let entry = queue.next() else {
            if queue.isEmpty { onIdle?() }
            return
        }
        busy = true
        let generation = self.generation
        switch entry.item {
        case .mp3(let data):
            guard let buffer = AudioEngine.decode(data, to: playFormat) else {
                busy = false
                next()
                return
            }
            do {
                if !engine.isRunning {
                    engine.prepare()
                    try engine.start()
                }
            } catch {
                busy = false
                next()
                return
            }
            started(entry.turn)
            player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack,
                                  completionHandler: AudioEngine.whenPlayed { [weak self] in
                guard let self, self.generation == generation else { return }
                self.busy = false
                self.next()
            })
            if !player.isPlaying { player.play() }
        case .say(let text):
            started(entry.turn)
            let utterance = AVSpeechUtterance(string: text)
            utterance.voice = AVSpeechSynthesisVoice(language: SpeechLanguage.of(text))
                ?? AVSpeechSynthesisVoice(language: "en-IN") ?? AVSpeechSynthesisVoice(language: "en-US")
            synthesizer.speak(utterance)
        }
    }

    nonisolated static func whenPlayed(
        _ then: @escaping @MainActor @Sendable () -> Void
    ) -> @Sendable (AVAudioPlayerNodeCompletionCallbackType) -> Void {
        { _ in Task { @MainActor in then() } }
    }

    private func started(_ turn: Int) {
        if !startedTurns.contains(turn) {
            startedTurns.insert(turn)
            onTurnStarted?(turn)
        }
    }

    /// Forget which turns have played (a new call numbers its turns from 1 again).
    public func newCall() {
        startedTurns.removeAll()
        queue = SpeechQueue()
        generation += 1
        busy = false
    }

    /// An MP3 sentence as PCM in the player's format. AVAudioFile reads files only,
    /// so the sentence passes through a temporary file that is removed at once.
    nonisolated static func decode(_ data: Data, to format: AVAudioFormat) -> AVAudioPCMBuffer? {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("ira-\(UUID().uuidString).mp3")
        defer { try? FileManager.default.removeItem(at: url) }
        do {
            try data.write(to: url, options: [.atomic])
            let file = try AVAudioFile(forReading: url)
            let frames = AVAudioFrameCount(file.length)
            guard frames > 0, let source = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: frames) else {
                return nil
            }
            try file.read(into: source)
            if source.format == format { return source }
            guard let converter = AVAudioConverter(from: source.format, to: format) else { return nil }
            let ratio = format.sampleRate / source.format.sampleRate
            guard let out = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(Double(frames) * ratio + 64)) else {
                return nil
            }
            let input = OneBuffer(source)
            var error: NSError?
            converter.convert(to: out, error: &error) { _, status in
                guard let next = input.take() else {
                    status.pointee = .endOfStream
                    return nil
                }
                status.pointee = .haveData
                return next
            }
            return error == nil ? out : nil
        } catch {
            return nil
        }
    }
}

extension AudioEngine: AVSpeechSynthesizerDelegate {
    nonisolated public func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in
            self.busy = false
            self.next()
        }
    }

    nonisolated public func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in self.busy = false }
    }
}

/// Converts the microphone's audio to 16 kHz mono floats, one buffer at a time,
/// on the audio thread (the converter keeps its state between buffers).
///
/// Float audio of several channels is first averaged over the channels that carry sound
/// (`Downmix`), then converted from mono; anything else goes to the converter as it is.
final class Resampler: @unchecked Sendable {
    private let converter: AVAudioConverter
    private let target: AVAudioFormat
    /// The mono format the channels are averaged into, when they are.
    private let mono: AVAudioFormat?
    private var failed = false

    init?(from format: AVAudioFormat) {
        guard let target = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16_000, channels: 1, interleaved: false)
        else { return nil }
        let several = format.channelCount > 1 && format.commonFormat == .pcmFormatFloat32
        let mono = several ? AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: format.sampleRate, channels: 1, interleaved: false) : nil
        guard let converter = AVAudioConverter(from: mono ?? format, to: target) else { return nil }
        converter.downmix = true
        self.converter = converter
        self.target = target
        self.mono = mono
    }

    /// A float buffer's channels, interleaved or not; empty for any other kind of sample.
    static func channels(_ buffer: AVAudioPCMBuffer) -> [[Float]] {
        guard let data = buffer.floatChannelData else { return [] }
        let count = Int(buffer.frameLength)
        let channels = Int(buffer.format.channelCount)
        if buffer.format.isInterleaved {
            let all = Array(UnsafeBufferPointer(start: data[0], count: count * channels))
            return (0..<channels).map { channel in stride(from: channel, to: all.count, by: channels).map { all[$0] } }
        }
        return (0..<channels).map { Array(UnsafeBufferPointer(start: data[$0], count: count)) }
    }

    func convert(_ buffer: AVAudioPCMBuffer, channels: [[Float]]? = nil) -> [Float]? {
        var source = buffer
        if let mono {
            let merged = Downmix.average(channels ?? Resampler.channels(buffer))
            guard let mixed = AVAudioPCMBuffer(pcmFormat: mono, frameCapacity: AVAudioFrameCount(merged.count)),
                let channel = mixed.floatChannelData?[0]
            else { return nil }
            merged.withUnsafeBufferPointer { channel.update(from: $0.baseAddress!, count: merged.count) }
            mixed.frameLength = AVAudioFrameCount(merged.count)
            source = mixed
        }
        let ratio = target.sampleRate / source.format.sampleRate
        let capacity = AVAudioFrameCount(Double(source.frameLength) * ratio + 32)
        guard let out = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity) else { return nil }
        let input = OneBuffer(source)
        var error: NSError?
        let status = converter.convert(to: out, error: &error) { _, status in
            guard let next = input.take() else {
                status.pointee = .noDataNow  // the converter keeps its state for the next buffer
                return nil
            }
            status.pointee = .haveData
            return next
        }
        guard status != .error, error == nil, let channel = out.floatChannelData?[0] else {
            if !failed {
                failed = true  // said once a listen: it would be said 50 times a second
                IraLog.shared.info("the microphone's audio could not be converted: \(error?.localizedDescription ?? "no reason given")")
            }
            return nil
        }
        return Array(UnsafeBufferPointer(start: channel, count: Int(out.frameLength)))
    }
}

/// Hands one buffer to AVAudioConverter, which asks for input synchronously,
/// during `convert`, on the calling thread.
final class OneBuffer: @unchecked Sendable {
    private var buffer: AVAudioPCMBuffer?

    init(_ buffer: AVAudioPCMBuffer) {
        self.buffer = buffer
    }

    func take() -> AVAudioPCMBuffer? {
        defer { buffer = nil }
        return buffer
    }
}

/// Cuts a stream of 16 kHz samples into 20 ms frames (320 samples), each with
/// the time it started.
public struct FrameChunker: Sendable {
    public static let frame = 320
    private var pending: [Float] = []
    private var pendingStart: Double = 0

    public init() {}

    /// Add samples that ended at `end` (ms); returns the whole frames now complete.
    public mutating func add(_ samples: [Float], endingAt end: Double) -> [([Float], Double)] {
        if pending.isEmpty {
            pendingStart = end - Double(samples.count) / 16.0
        }
        pending.append(contentsOf: samples)
        var frames: [([Float], Double)] = []
        while pending.count >= FrameChunker.frame {
            frames.append((Array(pending.prefix(FrameChunker.frame)), pendingStart))
            pending.removeFirst(FrameChunker.frame)
            pendingStart += 20
        }
        return frames
    }
}
