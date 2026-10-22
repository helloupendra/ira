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
        try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetooth])
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
        let input = engine.inputNode
        if !echoCancelling {
            do {
                try input.setVoiceProcessingEnabled(true)
                echoCancelling = true
            } catch {
                IraLog.shared.info("voice processing is not available here")
            }
        }
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            throw ToolFailure("no microphone is available")
        }
        guard let resampler = Resampler(from: format) else {
            throw ToolFailure("the microphone's audio could not be converted")
        }
        chunker = FrameChunker()
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format, block: AudioEngine.tap(resampler) { [weak self] samples, end in
            self?.collect(samples, endingAt: end)
        })
        if !engine.isRunning {
            engine.prepare()
            try engine.start()
        }
        listening = true
    }

    /// The tap runs on the audio thread: it converts there and hands the samples to
    /// the main actor. Made outside the actor, so it never claims to run on it.
    nonisolated static func tap(
        _ resampler: Resampler, deliver: @escaping @MainActor @Sendable ([Float], Double) -> Void
    ) -> AVAudioNodeTapBlock {
        { buffer, _ in
            let now = monotonicMs()
            guard let samples = resampler.convert(buffer) else { return }
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
            var fed = false
            var error: NSError?
            converter.convert(to: out, error: &error) { _, status in
                if fed {
                    status.pointee = .endOfStream
                    return nil
                }
                fed = true
                status.pointee = .haveData
                return source
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
final class Resampler: @unchecked Sendable {
    private let converter: AVAudioConverter
    private let target: AVAudioFormat

    init?(from format: AVAudioFormat) {
        guard let target = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16_000, channels: 1, interleaved: false),
            let converter = AVAudioConverter(from: format, to: target)
        else { return nil }
        converter.downmix = true  // a stereo or multichannel microphone becomes one voice
        self.converter = converter
        self.target = target
    }

    func convert(_ buffer: AVAudioPCMBuffer) -> [Float]? {
        let ratio = target.sampleRate / buffer.format.sampleRate
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio + 32)
        guard let out = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity) else { return nil }
        var fed = false
        var error: NSError?
        converter.convert(to: out, error: &error) { _, status in
            if fed {
                status.pointee = .noDataNow
                return nil
            }
            fed = true
            status.pointee = .haveData
            return buffer
        }
        guard error == nil, let channel = out.floatChannelData?[0] else { return nil }
        return Array(UnsafeBufferPointer(start: channel, count: Int(out.frameLength)))
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
