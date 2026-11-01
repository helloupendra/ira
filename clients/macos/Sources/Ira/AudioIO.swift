import AVFoundation
import CoreAudio
import Foundation
import IraKit

/// The microphone and the speaker, on one AVAudioEngine.
///
/// The engine's voice processing (echo cancellation) is switched on when the
/// Mac allows it, so Ira's own voice from the speakers is taken out of what the
/// microphone hears and only the person's voice interrupts her. Replies play
/// through the same engine for that reason.
@MainActor
final class AudioIO: NSObject {
    /// 16 kHz mono frames of 20 ms, with their start time (ms, `monotonicMs`).
    var onFrame: (([Float], Double) -> Void)?
    /// The first sound of a turn started playing.
    var onTurnStarted: ((Int) -> Void)?
    /// Nothing is left to play.
    var onIdle: (() -> Void)?
    /// How loud Ira's voice is now, as it plays (0 when silent): the lens's bars follow it.
    var onOutputLevel: ((Float) -> Void)?

    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let synthesizer = AVSpeechSynthesizer()
    private let playFormat = AVAudioFormat(standardFormatWithSampleRate: 24_000, channels: 1)!
    private var pending: [Float] = []
    private var pendingStart: Double = 0
    private(set) var listening = false
    private(set) var echoCancelling = false
    /// macOS said no to echo cancellation once in this run.
    private static var echoUnavailable = false

    private enum Item {
        case mp3(Data, turn: Int)
        case say(String, turn: Int)
    }
    private var queue: [Item] = []
    private var busy = false
    private var startedTurns: Set<Int> = []
    private var generation = 0

    var playing: Bool { busy || !queue.isEmpty }

    override init() {
        super.init()
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: playFormat)
        synthesizer.delegate = self
        // Ira's voice level as it plays, for the lens: on the audio thread, then the main one.
        player.installTap(onBus: 0, bufferSize: 1024, format: playFormat) { [weak self] buffer, _ in
            let level = EnergyVAD.rms(AudioIO.channels(buffer).first ?? [])
            Task { @MainActor in self?.onOutputLevel?(level) }
        }
    }

    nonisolated static var micPermission: AVAuthorizationStatus {
        AVCaptureDevice.authorizationStatus(for: .audio)
    }

    nonisolated static func askMicPermission() async -> Bool {
        guard !Snapshot.active else { return false }
        return await AVCaptureDevice.requestAccess(for: .audio)
    }

    /// The input the engine listens to: the Mac's default input, named as Sound settings names it.
    nonisolated static var inputName: String {
        var device = AudioObjectID(kAudioObjectUnknown)
        var size = UInt32(MemoryLayout<AudioObjectID>.size)
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDefaultInputDevice, mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &device) == noErr,
            device != kAudioObjectUnknown
        else { return "no input device" }
        var name: Unmanaged<CFString>?
        size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        address.mSelector = kAudioObjectPropertyName
        let status = withUnsafeMutablePointer(to: &name) { AudioObjectGetPropertyData(device, &address, 0, nil, &size, $0) }
        guard status == noErr, let name else { return "the default input" }
        return name.takeRetainedValue() as String
    }

    // MARK: Listening

    func startListening() throws {
        guard !listening else { return }
        let input = engine.inputNode
        if !echoCancelling && !AudioIO.echoUnavailable {
            do {
                try input.setVoiceProcessingEnabled(true)
                echoCancelling = true
            } catch {
                // Said once: this Mac's input cannot do it, and asking again changes nothing.
                AudioIO.echoUnavailable = true
                IraLog.shared.info("echo cancellation is not available on this Mac")
            }
        }
        if echoCancelling {
            // Voice processing's input gave pure zeros on a MacBook Air: make sure it is not
            // muted or bypassed, and that its own gain control is on.
            input.isVoiceProcessingInputMuted = false
            input.isVoiceProcessingBypassed = false
            input.isVoiceProcessingAGCEnabled = true
        }
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            throw ToolFailure("no microphone is connected")
        }
        let target = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16_000, channels: 1, interleaved: false)!
        // Several channels (voice processing gives that on some Macs, the voice in one of
        // them): they are averaged here, skipping empty ones, then made 16 kHz mono. The
        // converter alone would keep channel 0 only.
        let mono = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: format.sampleRate, channels: 1, interleaved: false)!
        let several = format.channelCount > 1 && format.commonFormat == .pcmFormatFloat32 && !format.isInterleaved
        let converter = AVAudioConverter(from: several ? mono : format, to: target)
        let probe = InputProbe(seconds: 1, sampleRate: format.sampleRate)
        let setup = "echo cancellation \(echoCancelling ? "on" : "off"), input \(Int(format.sampleRate)) Hz × \(format.channelCount) ch"
            + (echoCancelling ? ", muted \(input.isVoiceProcessingInputMuted), bypassed \(input.isVoiceProcessingBypassed), its gain control \(input.isVoiceProcessingAGCEnabled ? "on" : "off")" : "")
        pending = []
        input.removeTap(onBus: 0)
        // The tap runs on the audio thread: convert there, collect on the main thread.
        input.installTap(onBus: 0, bufferSize: 2048, format: format) { [weak self] buffer, _ in
            let now = monotonicMs()
            let channels = AudioIO.channels(buffer)
            if let levels = probe.add(channels) {
                let shown = levels.map { String(format: "%.4f", $0) }.joined(separator: ", ")
                IraLog.shared.info("listening: \(setup); first second, per channel: \(shown)")
            }
            let samples: [Float]?
            if several, let merged = AudioIO.buffer(Downmix.average(channels), format: mono) {
                samples = AudioIO.convert(merged, with: converter, to: target)
            } else {
                samples = AudioIO.convert(buffer, with: converter, to: target)
            }
            guard let samples else { return }
            Task { @MainActor in self?.collect(samples, endingAt: now) }
        }
        if !engine.isRunning {
            engine.prepare()
            try engine.start()
        }
        // Voice processing works on input and output together: keep the output side running
        // while listening, even with nothing to play.
        if !player.isPlaying { player.play() }
        listening = true
    }

    /// A buffer's channels, as float samples (empty when they are not float).
    nonisolated static func channels(_ buffer: AVAudioPCMBuffer) -> [[Float]] {
        guard let data = buffer.floatChannelData else { return [] }
        let count = Int(buffer.frameLength)
        if buffer.format.isInterleaved {
            let channels = Int(buffer.format.channelCount)
            let all = Array(UnsafeBufferPointer(start: data[0], count: count * channels))
            return (0..<channels).map { channel in stride(from: channel, to: all.count, by: channels).map { all[$0] } }
        }
        return (0..<Int(buffer.format.channelCount)).map { Array(UnsafeBufferPointer(start: data[$0], count: count)) }
    }

    /// Samples as a buffer of `format` (mono).
    nonisolated static func buffer(_ samples: [Float], format: AVAudioFormat) -> AVAudioPCMBuffer? {
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(samples.count)),
            let channel = buffer.floatChannelData?[0]
        else { return nil }
        samples.withUnsafeBufferPointer { channel.update(from: $0.baseAddress!, count: samples.count) }
        buffer.frameLength = AVAudioFrameCount(samples.count)
        return buffer
    }

    /// Listen again without voice processing. On some Macs its input gives only zeros, so a
    /// silent first listen tries once without it; echo cancellation then stays off this run.
    func restartWithoutEchoCancellation() throws {
        guard echoCancelling else { return }
        let wasListening = listening
        if wasListening { stopListening() }
        engine.stop()
        try engine.inputNode.setVoiceProcessingEnabled(false)
        echoCancelling = false
        AudioIO.echoUnavailable = true
        if wasListening { try startListening() }
    }

    func stopListening() {
        guard listening else { return }
        engine.inputNode.removeTap(onBus: 0)
        listening = false
        pending = []
        if !playing { engine.pause() }
    }

    nonisolated static func convert(_ buffer: AVAudioPCMBuffer, with converter: AVAudioConverter?, to format: AVAudioFormat) -> [Float]? {
        guard let converter else { return nil }
        let ratio = format.sampleRate / buffer.format.sampleRate
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio + 32)
        guard let out = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: capacity) else { return nil }
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

    /// Cut the stream into 20 ms frames (320 samples) with their start times.
    private func collect(_ samples: [Float], endingAt end: Double) {
        guard listening else { return }
        if pending.isEmpty {
            pendingStart = end - Double(samples.count) / 16.0
        }
        pending.append(contentsOf: samples)
        while pending.count >= 320 {
            let frame = Array(pending.prefix(320))
            pending.removeFirst(320)
            let at = pendingStart
            pendingStart += 20
            onFrame?(frame, at)
        }
    }

    // MARK: Speaking

    func play(mp3: Data, turn: Int) {
        queue.append(.mp3(mp3, turn: turn))
        next()
    }

    func say(_ text: String, turn: Int) {
        queue.append(.say(text, turn: turn))
        next()
    }

    /// Stop talking at once and forget what was queued (barge-in or stop).
    func stopPlayback() {
        generation += 1
        queue.removeAll()
        player.stop()
        if synthesizer.isSpeaking { synthesizer.stopSpeaking(at: .immediate) }
        busy = false
    }

    private func next() {
        guard !busy else { return }
        guard !queue.isEmpty else {
            onIdle?()
            return
        }
        let item = queue.removeFirst()
        busy = true
        let generation = self.generation
        switch item {
        case .mp3(let data, let turn):
            guard let buffer = decode(data) else {
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
            started(turn)
            player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
                Task { @MainActor in
                    guard let self, self.generation == generation else { return }
                    self.busy = false
                    self.next()
                }
            }
            if !player.isPlaying { player.play() }
        case .say(let text, let turn):
            started(turn)
            let utterance = AVSpeechUtterance(string: text)
            let devanagari = text.unicodeScalars.contains { (0x0900...0x097F).contains($0.value) }
            utterance.voice = AVSpeechSynthesisVoice(language: devanagari ? "hi-IN" : "en-IN")
                ?? AVSpeechSynthesisVoice(language: "en-US")
            synthesizer.speak(utterance)
        }
    }

    private func started(_ turn: Int) {
        if !startedTurns.contains(turn) {
            startedTurns.insert(turn)
            onTurnStarted?(turn)
        }
    }

    /// An MP3 sentence as PCM in the player's format. AVAudioFile reads files only,
    /// so the sentence passes through a temporary file that is removed at once.
    private func decode(_ data: Data) -> AVAudioPCMBuffer? {
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
            if source.format == playFormat { return source }
            guard let converter = AVAudioConverter(from: source.format, to: playFormat) else { return nil }
            let ratio = playFormat.sampleRate / source.format.sampleRate
            guard let out = AVAudioPCMBuffer(pcmFormat: playFormat, frameCapacity: AVAudioFrameCount(Double(frames) * ratio + 64)) else {
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

extension AudioIO: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didStart utterance: AVSpeechUtterance) {
        // The Mac's own voice plays outside the engine: a steady level keeps the bars moving.
        Task { @MainActor in self.onOutputLevel?(0.04) }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in
            self.onOutputLevel?(0)
            self.busy = false
            self.next()
        }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in
            self.onOutputLevel?(0)
            self.busy = false
        }
    }
}

/// What the input gives in the first second of a listen, per channel, for the log: once, so a
/// Mac whose microphone gives zeros (or speaks in another channel) says so.
final class InputProbe: @unchecked Sendable {
    private let lock = NSLock()
    private let wanted: Int
    private var squares: [Double] = []
    private var frames = 0
    private var told = false

    init(seconds: Double, sampleRate: Double) {
        wanted = max(1, Int(seconds * sampleRate))
    }

    /// One buffer's channels; each channel's RMS once a second has been heard, else nil.
    func add(_ channels: [[Float]]) -> [Float]? {
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
