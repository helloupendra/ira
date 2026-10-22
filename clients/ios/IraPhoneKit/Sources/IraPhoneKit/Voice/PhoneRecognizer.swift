import AVFoundation
import Foundation
import Speech

/// The iPhone's own speech recognition, for phone mode (a server without live
/// calls): one spoken turn at a time, fed the same 16 kHz frames the voice
/// detector sees, from the lead-in before speech to its end.
///
/// The language: the person's own (`mic_language` from their Ira: Hindi when
/// they speak Hindi or Hinglish), then Hindi, then Indian English, whichever the
/// iPhone has. On the iPhone itself when it can; otherwise iOS sends the audio
/// to Apple to recognise, as Siri's dictation does.
public final class PhoneRecognizer: @unchecked Sendable {
    public struct Unavailable: LocalizedError, Equatable {
        public let message: String
        public var errorDescription: String? { message }
    }

    /// The locales to try, in order, for a person whose own language is `preferred`.
    public static func locales(preferred: String?) -> [String] {
        var out: [String] = []
        for code in [preferred, "hi-IN", "en-IN"].compactMap({ $0 }) where !out.contains(code) {
            out.append(code)
        }
        return out
    }

    /// The first recognizer the iPhone has and can use now.
    public static func recognizer(preferred: String?) -> SFSpeechRecognizer? {
        for code in locales(preferred: preferred) {
            if let recognizer = SFSpeechRecognizer(locale: Locale(identifier: code)), recognizer.isAvailable {
                return recognizer
            }
        }
        return nil
    }

    private let recognizer: SFSpeechRecognizer
    private let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16_000, channels: 1, interleaved: false)!
    private let lock = NSLock()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var latest = ""
    private var waiting: CheckedContinuation<String, Never>?
    private var finished = false

    public var language: String { recognizer.locale.identifier }
    public var onDevice: Bool { recognizer.supportsOnDeviceRecognition }

    public init(preferred: String?) throws {
        guard let recognizer = PhoneRecognizer.recognizer(preferred: preferred) else {
            throw Unavailable(message: "The iPhone cannot recognise Hindi or English speech right now. Check it is online, or add the language under Settings, General, Keyboard, Dictation Languages. Typing still works.")
        }
        self.recognizer = recognizer
    }

    /// Start a turn.
    public func begin() {
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.taskHint = .dictation
        if recognizer.supportsOnDeviceRecognition { request.requiresOnDeviceRecognition = true }
        lock.withLock {
            self.request = request
            latest = ""
            finished = false
        }
        let task = recognizer.recognitionTask(with: request, resultHandler: PhoneRecognizer.handler(self))
        lock.withLock { self.task = task }
    }

    /// Made outside any actor: Speech calls it on its own queue.
    static func handler(_ owner: PhoneRecognizer) -> @Sendable (SFSpeechRecognitionResult?, Error?) -> Void {
        { [weak owner] result, error in
            guard let owner else { return }
            if let result {
                owner.heard(result.bestTranscription.formattedString, final: result.isFinal)
            } else if error != nil {
                owner.heard(nil, final: true)
            }
        }
    }

    private func heard(_ text: String?, final: Bool) {
        let done: (CheckedContinuation<String, Never>, String)? = lock.withLock {
            if let text { latest = text }
            guard final else { return nil }
            finished = true
            guard let waiting else { return nil }
            self.waiting = nil
            return (waiting, latest)
        }
        if let done { done.0.resume(returning: done.1) }
    }

    /// What has been heard so far, for the live caption.
    public var partial: String { lock.withLock { latest } }

    /// 20 ms of 16 kHz mono audio.
    public func append(_ samples: [Float]) {
        guard let request = lock.withLock({ self.request }),
            let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(samples.count))
        else { return }
        buffer.frameLength = AVAudioFrameCount(samples.count)
        if let channel = buffer.floatChannelData?[0] {
            samples.withUnsafeBufferPointer { channel.update(from: $0.baseAddress!, count: samples.count) }
        }
        request.append(buffer)
    }

    /// The turn is over: the final text (or the last partial, after `timeout`).
    public func end(timeout: Double = 3) async -> String {
        let request = lock.withLock { self.request }
        request?.endAudio()
        let text = await withCheckedContinuation { (continuation: CheckedContinuation<String, Never>) in
            let ready: String? = lock.withLock {
                if finished { return latest }
                waiting = continuation
                return nil
            }
            if let ready {
                continuation.resume(returning: ready)
                return
            }
            Task { [weak self] in
                try? await Task.sleep(nanoseconds: UInt64(timeout * 1_000_000_000))
                self?.heard(nil, final: true)
            }
        }
        lock.withLock {
            self.request = nil
            task = nil
        }
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Drop the turn in progress.
    public func cancel() {
        let task = lock.withLock {
            let task = self.task
            self.task = nil
            request = nil
            return task
        }
        task?.cancel()
        heard(nil, final: true)
    }
}
