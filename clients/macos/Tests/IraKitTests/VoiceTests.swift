import AppKit
import CoreText
import Foundation
import Testing
@testable import IraKit

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
    @Test func silenceIsNeverSpeech() {
        var vad = EnergyVAD()
        let out = Synth.run(&vad, Array(repeating: Synth.silence(), count: 100))
        #expect(out.isEmpty)
        #expect(!vad.speaking)
    }

    @Test func speechStartsWithItsLeadInAndEndsAfterTheHangover() {
        var vad = EnergyVAD()
        // 1 s quiet, 400 ms speech, 1 s quiet.
        let frames = Array(repeating: Synth.silence(), count: 50) + Array(repeating: Synth.tone(0.2), count: 20)
            + Array(repeating: Synth.silence(), count: 50)
        let out = Synth.run(&vad, frames)
        let starts = out.compactMap { if case .speechStart(let at) = $0.1 { return at } else { return nil } }
        let ends = out.compactMap { if case .speechEnd(let at) = $0.1 { return at } else { return nil } }
        #expect(starts == [1000])  // stamped where speech began, not when it was confirmed
        #expect(ends == [1400])  // the end of the last loud frame
        // It was confirmed after 60 ms (three frames), and the 300 ms before it came along.
        let firstAudio = out.firstIndex { if case .audio = $0.1 { return true } else { return false } }
        #expect(out[firstAudio!].0 == 1040)
        let leadIn = out.filter { $0.0 == 1040 }.filter { if case .audio = $0.1 { return true } else { return false } }
        #expect(leadIn.count == 15 + 3)  // 300 ms of lead-in and the three loud frames
        // The end came 600 ms after the last loud frame.
        let endFrame = out.first { if case .speechEnd = $0.1 { return true } else { return false } }
        #expect(endFrame?.0 == 1980)
        // Audio is 16-bit: 640 bytes a frame.
        if case .audio(let data) = out[firstAudio!].1 { #expect(data.count == 640) }
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
        // 3 s of a fan at about 0.015 RMS: below the base threshold, and learned as the room.
        let fan = (0..<150).map { _ in Synth.noise(0.026, seed: &seed) }
        #expect(Synth.run(&vad, fan).isEmpty)
        #expect(vad.noiseFloor > 0.01)
        #expect(vad.effectiveThreshold > EnergyVAD.Config().threshold)
        // Speech well above the fan still counts.
        let speech = Synth.run(&vad, Array(repeating: Synth.tone(0.3), count: 10))
        #expect(speech.contains { if case .speechStart = $0.1 { return true } else { return false } })
    }

    @Test func whileIraSpeaksItTakesALouderLongerVoice() {
        var vad = EnergyVAD()
        vad.replying = true
        // Ira's own voice leaking from the speakers at 0.03: not a barge-in.
        #expect(Synth.run(&vad, Array(repeating: Synth.tone(0.04), count: 30)).isEmpty)
        // A short loud burst (100 ms) is not enough either.
        var burst = EnergyVAD()
        burst.replying = true
        #expect(Synth.run(&burst, Array(repeating: Synth.tone(0.3), count: 5) + Array(repeating: Synth.silence(), count: 5)).isEmpty)
        // The person talking over Ira for 200 ms is.
        var person = EnergyVAD()
        person.replying = true
        let out = Synth.run(&person, Array(repeating: Synth.tone(0.3), count: 10))
        #expect(out.contains { if case .speechStart(let at) = $0.1 { return at == 0 } else { return false } })
    }

    @Test func pcmAndWav() {
        let pcm = PCM.int16Data([0, 1, -1, 0.5])
        #expect(pcm == Data([0x00, 0x00, 0xFF, 0x7F, 0x01, 0x80, 0xFF, 0x3F]))
        let wav = PCM.wav(pcm)
        #expect(wav.count == 44 + 8)
        #expect(String(decoding: wav.prefix(4), as: UTF8.self) == "RIFF")
        #expect(String(decoding: wav[8..<16], as: UTF8.self) == "WAVEfmt ")
        #expect(wav[24..<28] == Data([0x80, 0x3E, 0x00, 0x00]))  // 16,000 Hz
    }
}

@Suite("Streamed answers")
struct StreamingTests {
    @Test func sentencesCompleteAsTheyArrive() {
        var splitter = SentenceSplitter()
        #expect(splitter.feed("Theek hai. Tuesday has") == [])  // "Theek hai." is too short alone
        #expect(splitter.feed(" 14:00 free. And 3.5 hours") == ["Theek hai. Tuesday has 14:00 free."])
        #expect(splitter.feed(" later? Yes") == ["And 3.5 hours later?"])
        #expect(splitter.flush() == "Yes")
        #expect(splitter.flush() == nil)
        var hindi = SentenceSplitter()
        #expect(hindi.feed("फ़ाइल डाउनलोड फ़ोल्डर में है। ") == ["फ़ाइल डाउनलोड फ़ोल्डर में है।"])
        var lines = SentenceSplitter()
        #expect(lines.feed("- one\n- two\n") == ["- one", "- two"])
    }

    @Test func serverSentEvents() {
        var parser = SSEParser()
        #expect(parser.line(#"data: {"type":"start","conversation_id":"c1"}"#) == [])
        #expect(parser.line("") == [["type": "start", "conversation_id": "c1"]])
        #expect(parser.line(": keepalive") == [])
        // URLSession's lines drop blank ones: a new data line ends the event before it.
        #expect(parser.line(#"data: {"type":"delta","text":"Hi"}"#) == [])
        #expect(parser.line(#"data: {"type":"done","text":"Hi"}"#) == [["type": "delta", "text": "Hi"]])
        #expect(parser.finish() == [["type": "done", "text": "Hi"]])
    }
}

@Suite("Live voice")
struct LiveVoiceTests {
    func connect(_ channel: FakeChannel) -> (LiveVoiceTransport, FakeConnector) {
        let connector = FakeConnector(channel: channel)
        let live = try! LiveVoiceTransport(
            server: "https://ira.example.com", token: "irad_test", connector: connector, readyTimeout: 2,
            log: IraLog(directory: nil))
        return (live, connector)
    }

    @Test func aWholeTurnAsTheProtocolSays() async throws {
        let channel = FakeChannel()
        let (live, connector) = connect(channel)
        let events = EventLog<TalkEvent>()
        channel.push(["type": "ready", "protocol": 1, "conversation_id": "c9", "assistant": "Ira", "languages": ["en-IN", "hi-IN"], "tts": "polly"])
        try await live.start(conversationID: "c9") { events.add($0) }

        #expect(connector.seen.lastURL?.absoluteString == "wss://ira.example.com/v1/voice/live")
        #expect(connector.seen.lastHeaders["Authorization"] == "Bearer irad_test")
        let start = try #require(channel.sentJSON.first)
        #expect(start == ["type": "start", "protocol": 1, "client": .string(IraApp.userAgent), "conversation_id": "c9"])
        #expect(events.all == [.ready(conversationID: "c9", assistant: "Ira")])

        // The person speaks: speech_start, audio in binary frames, speech_end.
        live.speechStart(at: 1234.56)
        live.audio(Data(repeating: 1, count: 640 * 6))  // 120 ms: split into frames of 100 ms at most
        live.speechEnd(at: 2345.6)
        #expect(await channel.waitFor { $0.contains(["type": "speech_end", "at": 2345.6]) })
        #expect(channel.sentJSON.contains(["type": "speech_start", "at": 1234.6]))
        #expect(channel.sentData.map(\.count) == [3200, 640])

        // Ira answers.
        channel.push(["type": "partial", "text": "kal subah", "language": "hi-IN"])
        channel.push(["type": "heard", "turn": 1, "text": "kal subah 9 baje yaad dilana", "language": "hi-IN"])
        channel.push(["type": "delta", "turn": 1, "text": "Theek hai."])
        channel.push(["type": "audio", "turn": 1, "seq": 0, "text": "Theek hai.", "format": "mp3", "bytes": 3])
        channel.push(data: Data([0xFF, 0xFB, 0x90]))
        channel.push(["type": "action", "turn": 1, "action": ["id": "act_1", "tool": "remind_me", "summary": "Remind you at 9:00", "tier": 2]])
        channel.push(["type": "ping"])
        channel.push(["type": "done", "turn": 1, "text": "Theek hai.", "message_id": 812, "timings": ["stt_ms": 240]])
        #expect(await events.waitFor { $0.contains(.done(turn: 1, text: "Theek hai.")) })
        #expect(events.all.contains(.partial("kal subah")))
        #expect(events.all.contains(.heard(turn: 1, text: "kal subah 9 baje yaad dilana")))
        #expect(events.all.contains(.delta(turn: 1, text: "Theek hai.")))
        #expect(events.all.contains(.audio(turn: 1, seq: 0, text: "Theek hai.", data: Data([0xFF, 0xFB, 0x90]))))
        #expect(events.all.contains { if case .action(1, let action) = $0 { return action["id"] == "act_1" } else { return false } })
        #expect(await channel.waitFor { $0.contains(["type": "pong"]) })

        live.played(turn: 1, at: 3012.04)
        live.text("aur kuch?")
        live.interrupt()
        #expect(await channel.waitFor { sent in
            sent.contains(["type": "played", "turn": 1, "at": 3012]) && sent.contains(["type": "text", "text": "aur kuch?"])
                && sent.contains(["type": "interrupt"])
        })

        channel.push(["type": "interrupted", "turn": 2])
        channel.push(["type": "error", "message": "transcription failed", "fatal": false])
        #expect(await events.waitFor { $0.contains(.error("transcription failed", fatal: false)) })
        #expect(events.all.contains(.interrupted(turn: 2)))

        live.close()
        #expect(await channel.waitFor { $0.contains(["type": "bye"]) })
    }

    @Test func aServerWithoutLiveVoice() async {
        let connector = FakeConnector(channel: nil, error: WebSocketClosed(httpStatus: 404, reason: "not found"))
        let live = try! LiveVoiceTransport(server: "https://ira.example.com", token: "irad_test", connector: connector, log: IraLog(directory: nil))
        await #expect(throws: LiveUnavailable.self) { try await live.start(conversationID: nil) { _ in } }
    }

    @Test func aFatalErrorBeforeReady() async {
        let channel = FakeChannel()
        let (live, _) = connect(channel)
        channel.push(["type": "error", "message": "speech-to-text of type transcribe is needed", "fatal": true])
        await #expect(throws: LiveUnavailable("speech-to-text of type transcribe is needed")) {
            try await live.start(conversationID: nil) { _ in }
        }
        #expect(channel.closedWith != nil)
    }

    @Test func noAnswerInTime() async {
        let channel = FakeChannel()
        let connector = FakeConnector(channel: channel)
        let live = try! LiveVoiceTransport(server: "https://ira.example.com", token: "irad_test", connector: connector, readyTimeout: 0.2, log: IraLog(directory: nil))
        await #expect(throws: LiveUnavailable.self) { try await live.start(conversationID: nil) { _ in } }
    }

    @Test func audioForAnInterruptedTurnIsDropped() async throws {
        let channel = FakeChannel()
        let (live, _) = connect(channel)
        let events = EventLog<TalkEvent>()
        channel.push(["type": "ready", "protocol": 1])
        try await live.start(conversationID: nil) { events.add($0) }
        channel.push(["type": "audio", "turn": 3, "seq": 1, "text": "x", "format": "mp3", "bytes": 1])
        channel.push(["type": "interrupted", "turn": 3])
        channel.push(data: Data([1]))  // a frame no audio message announced: ignored
        channel.push(["type": "done", "turn": 3, "text": ""])
        #expect(await events.waitFor { $0.contains(.done(turn: 3, text: "")) })
        #expect(!events.all.contains { if case .audio = $0 { return true } else { return false } })
        live.close()
    }
}

@Suite("HTTP voice", .serialized)
struct HTTPVoiceTests {
    @Test func recordTranscribeAskSpeak() async throws {
        let host = "http-voice.example.com"
        let session = StubProtocol.session(host: host) { request, body in
            switch request.url?.path {
            case "/v1/info":
                return .init(status: 200, body: Data(#"{"name": "Ira", "tts": "polly", "permissions": ["ask", "voice"]}"#.utf8))
            case "/v1/voice/transcribe":
                #expect(request.value(forHTTPHeaderField: "Content-Type") == "audio/wav")
                #expect(body?.prefix(4) == Data("RIFF".utf8))
                return .init(status: 200, body: Data(#"{"text": "vo file kahan hai", "seconds": 1.2}"#.utf8))
            case "/v1/ask/stream":
                let asked = body.flatMap(JSONValue.parse)
                #expect(asked?["text"] == "vo file kahan hai")
                let lines = [
                    #"{"type": "start", "conversation_id": "c1"}"#,
                    #"{"type": "tool", "id": "t1", "name": "files_find", "arguments": {}}"#,
                    #"{"type": "delta", "text": "It is in your Downloads folder. "}"#,
                    #"{"type": "delta", "text": "Shall I open it?"}"#,
                    #"{"type": "done", "text": "It is in your Downloads folder. Shall I open it?", "model": "demo", "conversation_id": "c1"}"#,
                ]
                return .init(status: 200, body: Data(lines.map { "data: \($0)\n\n" }.joined().utf8), headers: ["Content-Type": "text/event-stream"])
            case "/v1/voice/speak":
                let text = body.flatMap(JSONValue.parse)?["text"]?.stringValue ?? ""
                return .init(status: 200, body: Data("MP3:\(text)".utf8), headers: ["Content-Type": "audio/mpeg"])
            default:
                return .init(status: 404, body: Data())
            }
        }
        let client = AskClient(server: "https://\(host)", session: session, token: { "irad_test" })
        let http = HTTPVoiceTransport(client: client, speakReplies: { false })
        let events = EventLog<TalkEvent>()
        try await http.start(conversationID: nil) { events.add($0) }
        http.speechStart(at: 0)
        http.audio(Data(repeating: 0, count: 6400))
        http.speechEnd(at: 200)
        #expect(await events.waitFor { $0.contains { if case .done = $0 { return true } else { return false } } })
        #expect(await events.waitFor { $0.filter { if case .audio = $0 { return true } else { return false } }.count == 2 })
        let all = events.all
        #expect(all.contains(.heard(turn: 1, text: "vo file kahan hai")))
        #expect(all.contains(.tool(turn: 1, name: "files_find")))
        #expect(all.contains(.ready(conversationID: "c1", assistant: nil)))
        let audio = all.compactMap { event -> String? in
            if case .audio(1, _, _, let data) = event { return String(decoding: data, as: UTF8.self) }
            return nil
        }
        #expect(audio == ["MP3:It is in your Downloads folder.", "MP3:Shall I open it?"])
        let authorization = StubProtocol.requests(host).map { $0.0.value(forHTTPHeaderField: "Authorization") }
        #expect(authorization.allSatisfy { $0 == "Bearer irad_test" })
        http.close()
    }

    @Test func aSignedOutSessionSaysSo() async {
        let host = "http-signed-out.example.com"
        let session = StubProtocol.session(host: host) { _, _ in .init(status: 401, body: Data(#"{"detail": "sign in"}"#.utf8)) }
        let http = HTTPVoiceTransport(client: AskClient(server: "https://\(host)", session: session, token: { "irad_old" }), speakReplies: { true })
        await #expect(throws: AskClient.Failure("sign in again to talk to Ira", status: 401)) {
            try await http.start(conversationID: nil) { _ in }
        }
    }
}

@Suite("Reading the screen")
struct ScreenTextTests {
    @Test func someWindowsAreNeverRead() {
        #expect(ScreenText.refusal(bundleID: "com.apple.systempreferences", name: "System Settings")?
            .hasPrefix("I can't read System Settings' window") == true)
        #expect(ScreenText.refusal(bundleID: "com.1password.1password", name: "1Password")?.contains("passwords") == true)
        #expect(ScreenText.refusal(bundleID: "com.google.Chrome", name: "Google Chrome") == nil)
        #expect(ScreenText.refusal(bundleID: nil, name: "Unknown") == nil)
    }

    @Test func aStuckToolAnswersBeforeTheServerGivesUp() {
        for tool in ToolCatalog.all(tasksConfigured: true).compactMap({ $0["name"]?.stringValue }) {
            #expect(Toolbox.deadline(for: tool) < 25, "\(tool)")
        }
        #expect(Toolbox.deadline(for: "screen_read") == 15)
        #expect(Toolbox.lateMessage("screen_read", screenPermitted: true) == ScreenText.restartNeeded)
        #expect(Toolbox.lateMessage("files_find", screenPermitted: false).contains("permission prompt"))
    }

    @Test func readingOrder() {
        let lines = [
            ScreenText.TextLine(text: "world", box: CGRect(x: 0.5, y: 0.8, width: 0.2, height: 0.05)),
            ScreenText.TextLine(text: "Second line", box: CGRect(x: 0.1, y: 0.6, width: 0.4, height: 0.05)),
            ScreenText.TextLine(text: "Hello", box: CGRect(x: 0.1, y: 0.81, width: 0.2, height: 0.05)),
        ]
        #expect(ScreenText.arrange(lines) == "Hello  world\nSecond line")
    }

    /// Vision reads text from a picture on this Mac, with no screen and no network.
    @Test func recognizesRenderedText() throws {
        let width = 900, height = 160
        let context = try #require(CGContext(
            data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0,
            space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        context.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        let font = CTFontCreateWithName("Helvetica" as CFString, 48, nil)
        let line = CTLineCreateWithAttributedString(NSAttributedString(
            string: "Upload 63% done", attributes: [.font: font]))
        context.textPosition = CGPoint(x: 40, y: 60)
        CTLineDraw(line, context)
        let image = try #require(context.makeImage())
        let text = try ScreenText.recognize(image, languages: ["en-US"])
        #expect(text.contains("63%"))
        #expect(text.lowercased().contains("upload"))
        #expect(ScreenText.languages().contains("en-US"))
    }
}
