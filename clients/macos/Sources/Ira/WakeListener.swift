import AVFoundation
import Foundation
import IraKit
import Speech

/// "Hey Ira": listens for the wake phrase on this Mac only.
///
/// Speech recognition runs on the Mac (`requiresOnDeviceRecognition`); no
/// audio and no words leave it until the phrase is heard, and then the
/// conversation starts as if the mic had been pressed. Off by default; the
/// menu-bar mark shows a dot while it listens. Recognition restarts every 50
/// seconds, because a single on-device request is meant for one utterance.
@MainActor
final class WakeListener {
    enum Problem: Error, LocalizedError {
        case notOnDevice, speechDenied, micDenied, noMicrophone

        var errorDescription: String? {
            switch self {
            case .notOnDevice:
                return "This Mac cannot recognise speech on its own for English, so “Hey Ira” stays off. Check that Siri and Dictation languages are downloaded in System Settings."
            case .speechDenied:
                return "“Hey Ira” needs Speech Recognition. Allow Ira in System Settings → Privacy & Security → Speech Recognition."
            case .micDenied:
                return "“Hey Ira” needs the microphone. Allow Ira in System Settings → Privacy & Security → Microphone."
            case .noMicrophone:
                return "No microphone is connected, so “Hey Ira” cannot listen."
            }
        }
    }

    var onWake: (() -> Void)?
    /// The person's wake phrase ("Hey Ira" unless they chose another).
    var phrase = "Hey Ira"
    private(set) var listening = false
    private let engine = AVAudioEngine()
    private var recognizer: SFSpeechRecognizer?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var restart: Timer?

    static func recognizer() -> SFSpeechRecognizer? {
        for locale in ["en-IN", "en-US"] {
            if let recognizer = SFSpeechRecognizer(locale: Locale(identifier: locale)), recognizer.supportsOnDeviceRecognition {
                return recognizer
            }
        }
        return nil
    }

    func start() async throws {
        guard !listening else { return }
        guard let recognizer = WakeListener.recognizer() else { throw Problem.notOnDevice }
        if SFSpeechRecognizer.authorizationStatus() == .notDetermined {
            await withCheckedContinuation { continuation in
                SFSpeechRecognizer.requestAuthorization { _ in continuation.resume() }
            }
        }
        guard SFSpeechRecognizer.authorizationStatus() == .authorized else { throw Problem.speechDenied }
        if AVCaptureDevice.authorizationStatus(for: .audio) == .notDetermined {
            _ = await AVCaptureDevice.requestAccess(for: .audio)
        }
        guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else { throw Problem.micDenied }
        self.recognizer = recognizer
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0 else { throw Problem.noMicrophone }
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 2048, format: format) { [weak self] buffer, _ in
            // The audio thread: hand the buffer to the current request only.
            Task { @MainActor in self?.request?.append(buffer) }
        }
        engine.prepare()
        try engine.start()
        listening = true
        begin()
        restart = Timer.scheduledTimer(withTimeInterval: 50, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.begin() }
        }
        IraLog.shared.info("wake phrase listening on")
    }

    /// A fresh recognition request (the previous one ends).
    private func begin() {
        task?.cancel()
        request?.endAudio()
        guard listening, let recognizer else { return }
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = true
        request.contextualStrings = [phrase, "Ira"]
        request.taskHint = .search
        self.request = request
        let phrase = self.phrase
        task = recognizer.recognitionTask(with: request) { [weak self] result, _ in
            guard let text = result?.bestTranscription.formattedString, WakePhrase.heard(text, phrase: phrase) else { return }
            Task { @MainActor in self?.woke() }
        }
    }

    private func woke() {
        guard listening else { return }
        IraLog.shared.info("wake phrase heard")
        stop()
        onWake?()
    }

    func stop() {
        guard listening else { return }
        listening = false
        restart?.invalidate()
        restart = nil
        task?.cancel()
        task = nil
        request?.endAudio()
        request = nil
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        IraLog.shared.info("wake phrase listening off")
    }
}
