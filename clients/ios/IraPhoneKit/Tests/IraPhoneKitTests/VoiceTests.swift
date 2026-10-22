import Foundation
import Testing
@testable import IraPhoneKit

/// Synthetic audio: 20 ms frames of 16 kHz.
enum Synth {
    static func silence() -> [Float] { [Float](repeating: 0, count: 320) }

    static func tone(_ amplitude: Float, frequency: Float = 220) -> [Float] {
        (0..<320).map { amplitude * sinf(2 * .pi * frequency * Float($0) / 16_000) }
    }

    static func noise(_ amplitude: Float, seed: inout UInt64) -> [Float] {
        (0..<320).map { _ in
            seed = seed &* 6364136223846793005 &+ 1442695040888963407
            return amplitude * (Float(seed >> 33) / Float(UInt32.max >> 1) - 1)
        }
    }

    /// Feed frames from 0 ms; collect every output with the frame's time.
    static func run(_ vad: inout EnergyVAD, _ frames: [[Float]]) -> [(Double, EnergyVAD.Output)] {
        var out: [(Double, EnergyVAD.Output)] = []
        for (index, frame) in frames.enumerated() {
            let at = Double(index) * 20
            out += vad.process(frame, at: at).map { (at, $0) }
        }
        return out
    }
}

@Suite("Voice detector")
struct VADTests {
    @Test func silenceIsNeverSent() {
        var vad = EnergyVAD()
        #expect(Synth.run(&vad, Array(repeating: Synth.silence(), count: 100)).isEmpty)
        #expect(!vad.speaking)
    }

    /// docs/realtime.md: audio from about 300 ms before speech began until speech_end,
    /// including the quiet of the hangover; speech_end stamped at the last spoken audio.
    @Test func audioRunsFromTheLeadInThroughTheQuietUntilSpeechEnd() {
        var vad = EnergyVAD()
        // 1 s quiet, 400 ms speech, 1 s quiet.
        let frames = Array(repeating: Synth.silence(), count: 50) + Array(repeating: Synth.tone(0.2), count: 20)
            + Array(repeating: Synth.silence(), count: 50)
        let out = Synth.run(&vad, frames)
        let starts = out.compactMap { if case .speechStart(let at) = $0.1 { return at } else { return nil } }
        let ends = out.compactMap { if case .speechEnd(let at) = $0.1 { return at } else { return nil } }
        #expect(starts == [1000])  // where speech began, not when it was confirmed
        #expect(ends == [1400])  // the end of the last loud frame
        let audio = out.filter { if case .audio = $0.1 { return true } else { return false } }
        // Confirmed after 60 ms: the 300 ms lead-in and the three loud frames go at once.
        #expect(audio.first?.0 == 1040)
        #expect(audio.filter { $0.0 == 1040 }.count == 15 + 3)
        // Then every frame until the end, quiet included: 1060 ms to 1980 ms.
        #expect(audio.last?.0 == 1980)
        #expect(audio.count == 18 + 47)
        // speech_end comes after the last audio of the turn, 600 ms after the last loud frame.
        let endIndex = out.firstIndex { if case .speechEnd = $0.1 { return true } else { return false } }!
        #expect(out[endIndex].0 == 1980)
        #expect(!out[(endIndex + 1)...].contains { if case .audio = $0.1 { return true } else { return false } })
        if case .audio(let data) = audio[0].1 { #expect(data.count == 640) }  // 16-bit PCM, 20 ms
    }

    @Test func aClickIsNotSpeech() {
        var vad = EnergyVAD()
        let frames = Array(repeating: Synth.silence(), count: 10) + [Synth.tone(0.5), Synth.tone(0.5)]
            + Array(repeating: Synth.silence(), count: 40)
        #expect(Synth.run(&vad, frames).isEmpty)
    }

    @Test func aSteadyFanRaisesTheThreshold() {
        var vad = EnergyVAD()
        var seed: UInt64 = 7
        let fan = (0..<150).map { _ in Synth.noise(0.026, seed: &seed) }
        #expect(Synth.run(&vad, fan).isEmpty)
        #expect(vad.noiseFloor > 0.01)
        #expect(vad.effectiveThreshold > EnergyVAD.Config().threshold)
        let speech = Synth.run(&vad, Array(repeating: Synth.tone(0.3), count: 10))
        #expect(speech.contains { if case .speechStart = $0.1 { return true } else { return false } })
    }

    @Test func whileIraSpeaksOnlyALouderLongerVoiceBargesIn() {
        var vad = EnergyVAD()
        vad.replying = true
        #expect(Synth.run(&vad, Array(repeating: Synth.tone(0.04), count: 30)).isEmpty)
        var burst = EnergyVAD()
        burst.replying = true
        #expect(Synth.run(&burst, Array(repeating: Synth.tone(0.3), count: 5) + Array(repeating: Synth.silence(), count: 5)).isEmpty)
        var person = EnergyVAD()
        person.replying = true
        let out = Synth.run(&person, Array(repeating: Synth.tone(0.3), count: 10))
        #expect(out.contains { if case .speechStart(let at) = $0.1 { return at == 0 } else { return false } })
    }

    @Test func aLongMonologueStillEnds() {
        var config = EnergyVAD.Config()
        config.maxSpeechMs = 1000
        var vad = EnergyVAD(config: config)
        let out = Synth.run(&vad, Array(repeating: Synth.tone(0.3), count: 80))
        #expect(out.contains { if case .speechEnd = $0.1 { return true } else { return false } })
    }

    @Test func pcm() {
        let data = PCM.int16Data([0, 1, -1, 0.5])
        #expect(data == Data([0x00, 0x00, 0xFF, 0x7F, 0x01, 0x80, 0xFF, 0x3F]))
        let back = PCM.floats(data)
        #expect(back.count == 4)
        #expect(back[0] == 0 && back[1] == 1 && back[2] == -1 && abs(back[3] - 0.5) < 0.001)
        #expect(PCM.floats(data.dropFirst(2)).count == 3)  // a slice keeps its own indices
    }
}

@Suite("Microphone frames")
struct FrameChunkerTests {
    @Test func twentyMillisecondFramesWithTheirTimes() {
        var chunker = FrameChunker()
        // 1024 samples (64 ms) that ended at 1064 ms: they began at 1000 ms.
        let first = chunker.add([Float](repeating: 0.1, count: 1024), endingAt: 1064)
        #expect(first.map(\.1) == [1000, 1020, 1040])
        #expect(first.allSatisfy { $0.0.count == 320 })
        // 64 left over; 256 more make one frame, which goes on from 1060 ms.
        let second = chunker.add([Float](repeating: 0.1, count: 256), endingAt: 1080)
        #expect(second.map(\.1) == [1060])
    }
}

@Suite("Speaking in order")
struct SpeechQueueTests {
    /// The next sentence to play, or nil.
    func take(_ queue: inout SpeechQueue<String>) -> String? { queue.next()?.item }

    @Test func sentencesPlayBySeqWhateverOrderTheyArrive() {
        var queue = SpeechQueue<String>()
        queue.add(turn: 1, seq: 1, "second")
        #expect(take(&queue) == nil)  // the first has not come yet
        queue.add(turn: 1, seq: 0, "first")
        #expect(take(&queue) == "first")
        #expect(take(&queue) == "second")
        #expect(take(&queue) == nil)
        let again = queue.add(turn: 1, seq: 0, "again")
        #expect(!again)  // never twice
    }

    @Test func aNewerTurnWaitsForTheOlderOne() {
        var queue = SpeechQueue<String>()
        queue.add(turn: 2, seq: 0, "turn two")
        queue.add(turn: 1, seq: 0, "turn one")
        #expect(take(&queue) == "turn one")
        #expect(take(&queue) == "turn two")
    }

    @Test func aBargeInDropsTheTurnAndAnythingLateForIt() {
        var queue = SpeechQueue<String>()
        queue.add(turn: 3, seq: 0, "a")
        queue.add(turn: 3, seq: 1, "b")
        #expect(take(&queue) == "a")
        queue.stop(through: 3)
        #expect(take(&queue) == nil)
        #expect(queue.isEmpty)
        let late = queue.add(turn: 3, seq: 2, "late")
        #expect(!late)
        let next = queue.add(turn: 4, seq: 0, "next turn")
        #expect(next)
        #expect(take(&queue) == "next turn")
    }

    @Test func aMissingSentenceCanBeSkipped() {
        var queue = SpeechQueue<String>()
        queue.add(turn: 1, seq: 1, "after the gap")
        queue.skip(turn: 1, seq: 0)
        #expect(take(&queue) == "after the gap")
    }
}

@Suite("Sentences")
struct SentenceTests {
    @Test func sentencesCompleteAsTheyArrive() {
        var splitter = SentenceSplitter()
        #expect(splitter.feed("Theek hai. Tuesday has") == [])
        #expect(splitter.feed(" 14:00 free. And 3.5 hours") == ["Theek hai. Tuesday has 14:00 free."])
        #expect(splitter.feed(" later? Yes") == ["And 3.5 hours later?"])
        #expect(splitter.flush() == "Yes")
        #expect(splitter.flush() == nil)
        var hindi = SentenceSplitter()
        #expect(hindi.feed("कल सुबह नौ बजे की मीटिंग है। ") == ["कल सुबह नौ बजे की मीटिंग है।"])
    }

    @Test func theIPhonesVoiceFollowsTheScript() {
        #expect(SpeechLanguage.of("कल सुबह") == "hi-IN")
        #expect(SpeechLanguage.of("kal subah 9 baje") == "en-IN")
    }

    @Test func phoneRecognitionTriesThePersonsLanguageFirst() {
        #expect(PhoneRecognizer.locales(preferred: "en-IN") == ["en-IN", "hi-IN"])
        #expect(PhoneRecognizer.locales(preferred: "hi-IN") == ["hi-IN", "en-IN"])
        #expect(PhoneRecognizer.locales(preferred: nil) == ["hi-IN", "en-IN"])
    }
}
