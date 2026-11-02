package io.github.helloupendra.ira.core

import kotlin.math.sqrt

/**
 * A simple energy voice detector, run on the phone on 20 ms frames of 16 kHz audio.
 * The same rules as the Mac app's (`clients/macos/Sources/IraKit/Voice/VAD.swift`):
 *
 * - Speech starts when the level stays above the threshold for [Config.startMs] (160 ms),
 *   so a click or a cough does not count.
 * - When it starts, the last [Config.leadInMs] (about 300 ms) before it are sent too, so
 *   the first syllable is not cut.
 * - Speech ends after [Config.hangoverMs] (about 900 ms) of quiet: a breath is not the end. The quiet is sent too
 *   (it lets the transcript settle on the last word); the end is stamped at the last loud
 *   frame's end, not when the hangover ran out.
 * - The threshold follows the room: at least [Config.threshold], and at least
 *   [Config.noiseFactor] times the quiet level heard so far, so a fan does not count.
 * - While Ira is speaking ([replying]), the threshold is raised and speech must last
 *   longer before it counts, so Ira's own voice from the speaker rarely interrupts her;
 *   the person's voice does (barge-in).
 */
class EnergyVad(val config: Config = Config()) {
    data class Config(
        val sampleRate: Int = 16_000,
        val frameMs: Double = 20.0,
        val threshold: Float = 0.02f,
        val startMs: Double = 160.0,
        val hangoverMs: Double = 900.0,
        val leadInMs: Double = 300.0,
        val maxSpeechMs: Double = 60_000.0,
        val noiseFactor: Float = 3f,
        /** While Ira speaks, the bar is this many times her voice at the microphone... */
        val replyFactor: Float = 2.5f,
        /** ...but never past a level a normal voice reaches. */
        val replyCeiling: Float = 0.15f,
        /** How fast her voice's level is learned, up and down, per frame: over a second or two. */
        val echoRise: Float = 0.02f,
        val echoFall: Float = 0.01f,
        val replyStartMs: Double = 200.0,
        /** Quiet within the start of speech that does not break it: dips between syllables. */
        val gapMs: Double = 80.0,
    )

    sealed interface Output {
        /** Speech began at this time (ms, the caller's monotonic clock). */
        data class SpeechStart(val at: Double) : Output

        /** Audio to send: 16-bit little-endian mono PCM. */
        class Audio(val pcm: ByteArray) : Output

        /** Speech ended at this time: the end of the last loud frame. */
        data class SpeechEnd(val at: Double) : Output
    }

    var replying: Boolean = false
    var speaking: Boolean = false
        private set
    var noiseFloor: Float = 0f
        private set
    var level: Float = 0f
        private set

    private class Frame(val at: Double, val pcm: ByteArray)

    private val recent = ArrayDeque<Frame>()
    private var loudRun = 0
    private var runStart = 0.0
    private var quietRun = 0
    private var lastLoudEnd = 0.0
    private var speechStarted = 0.0

    /** The bar with Ira quiet. The room can raise it, but never past a level normal speech reaches. */
    val baseThreshold: Float
        get() = maxOf(config.threshold, minOf(noiseFloor * config.noiseFactor, 0.12f))

    /**
     * How loud Ira's own voice reaches the microphone, learned while she speaks. Echo cancelling
     * leaves little of it, and a fixed bar over that kept a voice from being heard over hers;
     * where much is left, the bar rises with it.
     */
    @Volatile
    var echoLevel: Float = config.threshold
        private set

    val effectiveThreshold: Float
        get() = if (replying) maxOf(baseThreshold, minOf(echoLevel * config.replyFactor, config.replyCeiling)) else baseThreshold

    /** Feed one frame of 16-bit samples that starts at [at] (ms); returns what to do now. */
    fun process(samples: ShortArray, at: Double): List<Output> {
        val level = rms(samples)
        this.level = level
        val pcm = Pcm.toBytes(samples)
        val end = at + samples.size * 1000.0 / config.sampleRate
        val loud = level > effectiveThreshold
        val out = ArrayList<Output>(2)
        if (replying && !speaking) {
            echoLevel += (level - echoLevel) * (if (level > echoLevel) config.echoRise else config.echoFall)
        }

        if (!speaking) {
            if (!loud && !replying) {
                // Learn the room's quiet level, slowly, only from quiet frames.
                noiseFloor = if (noiseFloor == 0f) level else noiseFloor * 0.95f + level * 0.05f
            }
            recent.addLast(Frame(at, pcm))
            val keep = ((config.leadInMs + config.replyStartMs) / config.frameMs).toInt() + 1
            while (recent.size > keep) recent.removeFirst()
            if (loud) {
                if (loudRun == 0) runStart = at
                loudRun++
                quietRun = 0
                lastLoudEnd = end
            } else if (loudRun > 0) {
                // A dip of up to gapMs between syllables keeps the run; a longer one ends it.
                quietRun++
                if (quietRun * config.frameMs > config.gapMs) {
                    loudRun = 0
                    quietRun = 0
                }
            }
            val needed = if (replying) config.replyStartMs else config.startMs
            if (loud && loudRun > 0 && end - runStart >= needed) {
                speaking = true
                speechStarted = runStart
                out.add(Output.SpeechStart(runStart))
                // The lead-in: up to leadInMs before the speech, then the speech so far.
                val from = runStart - config.leadInMs
                for (frame in recent) if (frame.at >= from - 0.001) out.add(Output.Audio(frame.pcm))
                recent.clear()
                loudRun = 0
                quietRun = 0
            }
            return out
        }

        out.add(Output.Audio(pcm))
        if (loud) lastLoudEnd = end
        if (end - lastLoudEnd >= config.hangoverMs || end - speechStarted >= config.maxSpeechMs) {
            speaking = false
            out.add(Output.SpeechEnd(lastLoudEnd))
        }
        return out
    }

    /** Forget any speech in progress (the person pressed stop). */
    fun reset() {
        speaking = false
        recent.clear()
        loudRun = 0
        quietRun = 0
    }

    companion object {
        /** The level of a frame: its root mean square, 0 to 1. */
        fun rms(samples: ShortArray): Float {
            if (samples.isEmpty()) return 0f
            var sum = 0.0
            for (s in samples) {
                val v = s / 32768.0
                sum += v * v
            }
            return sqrt(sum / samples.size).toFloat()
        }
    }
}

/** 16-bit PCM helpers. */
object Pcm {
    fun toBytes(samples: ShortArray): ByteArray {
        val out = ByteArray(samples.size * 2)
        for (i in samples.indices) {
            val v = samples[i].toInt()
            out[2 * i] = (v and 0xff).toByte()
            out[2 * i + 1] = ((v shr 8) and 0xff).toByte()
        }
        return out
    }

    fun toSamples(bytes: ByteArray): ShortArray {
        val out = ShortArray(bytes.size / 2)
        for (i in out.indices) {
            out[i] = ((bytes[2 * i].toInt() and 0xff) or (bytes[2 * i + 1].toInt() shl 8)).toShort()
        }
        return out
    }
}
