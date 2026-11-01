import AVFoundation
import Testing
@testable import Ira

/// The microphone's buffers as the listening tap reads them: every channel, not channel 0
/// alone, and what the first second of a listen gave, for the log. No microphone is used.
@Suite("The microphone's input")
struct AudioInputTests {
    func buffer(channels: [[Float]], interleaved: Bool) throws -> AVAudioPCMBuffer {
        let format = try #require(AVAudioFormat(
            commonFormat: .pcmFormatFloat32, sampleRate: 48_000, channels: AVAudioChannelCount(channels.count), interleaved: interleaved))
        let frames = channels[0].count
        let buffer = try #require(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frames)))
        buffer.frameLength = AVAudioFrameCount(frames)
        let data = try #require(buffer.floatChannelData)
        for (channel, samples) in channels.enumerated() {
            for (index, sample) in samples.enumerated() {
                if interleaved {
                    data[0][index * channels.count + channel] = sample
                } else {
                    data[channel][index] = sample
                }
            }
        }
        return buffer
    }

    @Test func everyChannelIsRead() throws {
        // Channel 0 empty, the voice in channel 1: as voice processing gives it on some Macs.
        let channels: [[Float]] = [[0, 0, 0, 0], [0.1, -0.1, 0.2, -0.2]]
        #expect(AudioIO.channels(try buffer(channels: channels, interleaved: false)) == channels)
        #expect(AudioIO.channels(try buffer(channels: channels, interleaved: true)) == channels)
    }

    @Test func monoSamplesBecomeABuffer() throws {
        let format = try #require(AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48_000, channels: 1, interleaved: false))
        let made = try #require(AudioIO.buffer([0.1, 0.2, 0.3], format: format))
        #expect(AudioIO.channels(made) == [[0.1, 0.2, 0.3]])
    }

    @Test func theFirstSecondIsToldOnce() {
        let probe = InputProbe(seconds: 1, sampleRate: 4)
        #expect(probe.add([[0, 0], [0.5, -0.5]]) == nil)
        #expect(probe.add([[0, 0], [0.5, -0.5]]) == [0, 0.5])
        #expect(probe.add([[1, 1], [1, 1]]) == nil)  // once per listen
    }
}
