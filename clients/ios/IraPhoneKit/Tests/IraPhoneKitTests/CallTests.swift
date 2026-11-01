import Foundation
import Testing
@testable import IraPhoneKit

@Suite("What a call shows")
struct CallPhaseTests {
    @Test func oneWordForEachMoment() {
        func phase(connecting: Bool = false, hearing: Bool = false, speaking: Bool = false, thinking: Bool = false, silent: Bool = false) -> CallPhase {
            CallPhase.of(connecting: connecting, hearing: hearing, speaking: speaking, thinking: thinking, micSilent: silent)
        }
        #expect(phase() == .listening)
        #expect(phase(hearing: true) == .hearing)
        #expect(phase(thinking: true) == .thinking)
        #expect(phase(speaking: true, thinking: true) == .speaking)  // what the person hears comes first
        #expect(phase(connecting: true, speaking: true) == .connecting)
        // A silent microphone shows only when nothing else is going on.
        #expect(phase(silent: true) == .micSilent)
        #expect(phase(thinking: true, silent: true) == .thinking)
        #expect(CallPhase.listening.title == "Listening")
        #expect(CallPhase.hearing.title == "Hearing you")
        #expect(CallPhase.micSilent.detail.contains("microphone"))
    }

    @Test func theWaveformKeepsTheLastLevels() {
        var history = LevelHistory(count: 4)
        #expect(history.levels == [0, 0, 0, 0])
        for level: Float in [0.1, 0.2, 0.3, 0.4, 0.5] { history.add(level) }
        #expect(history.levels == [0.2, 0.3, 0.4, 0.5])
        history.add(-1)
        #expect(history.levels.last == 0)
        history.clear()
        #expect(history.levels == [0, 0, 0, 0])
    }
}

@Suite("A microphone that gives nothing")
struct MicWatchTests {
    @Test func pureZerosOrNoAudioAtAllIsSilent() {
        var watch = MicWatch(afterMs: 3000)
        watch.start(at: 0)
        // Audio that never arrives: the timer finds it.
        let silent1 = watch.check(now: 2900)
        #expect(!silent1)
        let silent2 = watch.check(now: 3100)
        #expect(silent2)
        // Frames of pure zeros do not count as sound.
        watch.frame(level: 0, at: 3200)
        let silent3 = watch.check(now: 3300)
        #expect(silent3)
        // One real sound clears it, and a real room keeps it clear.
        watch.frame(level: 0.002, at: 3400)
        #expect(!watch.silent)
        let silent4 = watch.check(now: 5000)
        #expect(!silent4)
        // Sound that stops for good is silence again.
        let silent5 = watch.check(now: 6500)
        #expect(silent5)
    }

    @Test func aQuietPersonIsNotSilent() {
        var watch = MicWatch()
        watch.start(at: 0)
        for at in stride(from: 0.0, through: 10_000, by: 20) {
            watch.frame(level: 0.0004, at: at)  // a quiet room, below any voice threshold
        }
        let silent6 = watch.check(now: 10_000)
        #expect(!silent6)
    }

    @Test func stoppedIsNeverSilent() {
        var watch = MicWatch()
        let silent7 = watch.check(now: 100_000)
        #expect(!silent7)
        watch.start(at: 0)
        watch.stop()
        let silent8 = watch.check(now: 100_000)
        #expect(!silent8)
    }
}

@Suite("Receipts")
struct ReceiptTests {
    @Test func theToolsIraUsedStayWithTheAnswer() {
        var transcript = Transcript()
        transcript.said("kal ka schedule?", source: 1001, turn: 1)
        transcript.apply(.tool(turn: 1, name: "calendar_read"), source: 1001)
        transcript.apply(.tool(turn: 1, name: "calendar_read"), source: 1001)  // the same one again: once
        transcript.apply(.tool(turn: 1, name: "contacts_lookup"), source: 1001)
        transcript.apply(.delta(turn: 1, text: "Kal do meetings hain."), source: 1001)
        transcript.apply(.done(turn: 1, text: "Kal do meetings hain.", messageID: 7), source: 1001)
        let answers = transcript.entries.filter { $0.role == .ira }
        #expect(answers.count == 1)
        #expect(answers[0].tools == ["calendar_read", "contacts_lookup"])
        #expect(answers[0].text == "Kal do meetings hain.")
        #expect(!answers[0].streaming)
        // Another turn's tools are its own.
        transcript.apply(.tool(turn: 2, name: "web_search"), source: 1001)
        #expect(transcript.entries.last?.tools == ["web_search"])
    }
}

@Suite("Appearance")
struct LookTests {
    @Test func followsTheIPhoneUntilChosen() {
        let defaults = UserDefaults(suiteName: "ira-look-\(UUID().uuidString)")!
        let settings = AppSettings(defaults: defaults)
        #expect(settings.look == "system")
        settings.look = "dark"
        #expect(settings.look == "dark")
        defaults.set("purple", forKey: "look")
        #expect(settings.look == "system")
    }
}

@Suite("The microphone's channels")
struct InputMixTests {
    @Test func theVoiceIsKeptFromWhicheverChannelsCarryIt() {
        // Voice processing with the voice in the second channel only: the first is empty.
        let voice: [Float] = [0.1, -0.2, 0.3, -0.1]
        #expect(Downmix.average([[0, 0, 0, 0], voice]) == voice)
        #expect(Downmix.average([voice, voice]) == voice)
        #expect(Downmix.average([[0, 0], [0, 0]]) == [0, 0])
        #expect(Downmix.average([]) == [])
    }

    @Test func theFirstSecondIsReportedAndPureZerosAreSilent() {
        let probe = InputProbe(seconds: 0.5, sampleRate: 8)  // four samples
        #expect(probe.add([[0, 0]]) == nil)
        let levels = probe.add([[0, 0]])
        #expect(levels == [0])
        #expect(probe.add([[1, 1]]) == nil)  // once a listen
        #expect(InputProbe.describe(setup: "48000 Hz × 1 ch, echo cancellation on", levels: [0])
            == "48000 Hz × 1 ch, echo cancellation on: silent (0.0000)")
        #expect(InputProbe.describe(setup: "x", levels: [0, 0.0123]).hasSuffix("sound (0.0000, 0.0123)"))
    }
}
