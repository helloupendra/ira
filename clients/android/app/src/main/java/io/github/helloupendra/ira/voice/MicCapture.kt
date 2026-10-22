package io.github.helloupendra.ira.voice

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import android.os.SystemClock
import io.github.helloupendra.ira.core.LiveProtocol
import io.github.helloupendra.ira.net.IraLog

/**
 * The microphone, read in 20 ms frames of 16 kHz mono 16-bit PCM on a thread of its own.
 *
 * It runs only while a conversation is on. Nothing is written to storage: each frame goes
 * to the voice detector, and only the frames it marks as speech leave the phone.
 * The voice-communication source turns on the phone's echo canceller where it has one,
 * so Ira's own voice from the speaker rarely counts as the person speaking.
 */
class MicCapture(private val context: Context, private val onFrame: (ShortArray, Double) -> Unit) {
    private var thread: Thread? = null

    @Volatile
    private var running = false

    val frameSamples: Int = LiveProtocol.SAMPLE_RATE / 50 // 20 ms

    fun hasPermission(): Boolean =
        context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    @SuppressLint("MissingPermission") // checked in start()
    fun start(): Boolean {
        if (running) return true
        if (!hasPermission()) return false
        val minimum =
            AudioRecord.getMinBufferSize(
                LiveProtocol.SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
            )
        if (minimum <= 0) return false
        val record =
            try {
                AudioRecord(
                    MediaRecorder.AudioSource.VOICE_COMMUNICATION,
                    LiveProtocol.SAMPLE_RATE,
                    AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT,
                    maxOf(minimum, frameSamples * 2 * 10),
                )
            } catch (exc: Exception) {
                IraLog.warn("mic: could not open", exc)
                return false
            }
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            return false
        }
        val echo = if (AcousticEchoCanceler.isAvailable()) AcousticEchoCanceler.create(record.audioSessionId) else null
        echo?.enabled = true
        val noise = if (NoiseSuppressor.isAvailable()) NoiseSuppressor.create(record.audioSessionId) else null
        noise?.enabled = true
        running = true
        thread =
            Thread({
                android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_URGENT_AUDIO)
                val frame = ShortArray(frameSamples)
                try {
                    record.startRecording()
                    while (running) {
                        var filled = 0
                        while (filled < frameSamples && running) {
                            val n = record.read(frame, filled, frameSamples - filled)
                            if (n < 0) {
                                running = false
                                break
                            }
                            filled += n
                        }
                        if (filled == frameSamples) {
                            // The frame's start, on the same monotonic clock as every message.
                            val at = SystemClock.elapsedRealtimeNanos() / 1e6 - 20.0
                            onFrame(frame.copyOf(), at)
                        }
                    }
                } catch (exc: Exception) {
                    IraLog.warn("mic: stopped", exc)
                } finally {
                    try {
                        record.stop()
                    } catch (_: Exception) {
                    }
                    echo?.release()
                    noise?.release()
                    record.release()
                }
            }, "ira-mic").apply { start() }
        return true
    }

    fun stop() {
        running = false
        thread?.join(500)
        thread = null
    }
}

/** The monotonic clock every live message uses, in milliseconds. */
fun nowMs(): Double = SystemClock.elapsedRealtimeNanos() / 1e6
