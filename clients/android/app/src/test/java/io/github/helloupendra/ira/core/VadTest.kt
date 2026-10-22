package io.github.helloupendra.ira.core

import kotlin.math.PI
import kotlin.math.sin
import kotlin.random.Random
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The voice detector on synthetic 16 kHz audio: 20 ms frames of silence, noise and tone. */
class VadTest {
    private val frame = 320

    private fun tone(amplitude: Double, hz: Double = 220.0) =
        ShortArray(frame) { (sin(2 * PI * hz * it / 16_000) * amplitude * 32767).toInt().toShort() }

    private fun noise(amplitude: Double, random: Random) =
        ShortArray(frame) { ((random.nextDouble() * 2 - 1) * amplitude * 32767).toInt().toShort() }

    private val silence = ShortArray(frame)

    /** Feed frames from t = 0 ms, 20 ms apart; returns every output with its frame time. */
    private fun run(vad: EnergyVad, frames: List<ShortArray>, start: Double = 0.0): List<Pair<Double, EnergyVad.Output>> {
        val out = ArrayList<Pair<Double, EnergyVad.Output>>()
        frames.forEachIndexed { i, f -> vad.process(f, start + i * 20.0).forEach { out += (start + i * 20.0) to it } }
        return out
    }

    private fun repeat(f: ShortArray, n: Int) = List(n) { f }

    @Test
    fun `silence is never sent`() {
        val out = run(EnergyVad(), repeat(silence, 100))
        assertTrue(out.isEmpty())
    }

    @Test
    fun `speech starts after 60 ms of voice, with about 300 ms of lead-in`() {
        val vad = EnergyVad()
        val out = run(vad, repeat(silence, 30) + repeat(tone(0.2), 10))
        val start = out.first { it.second is EnergyVad.Output.SpeechStart }
        assertEquals(600.0, (start.second as EnergyVad.Output.SpeechStart).at, 0.001)
        // Started on the third loud frame (600 + 60 ms), with 300 ms before it and the 3 loud frames.
        assertEquals(640.0, start.first, 0.001)
        val lead = out.takeWhile { it.first == start.first }.count { it.second is EnergyVad.Output.Audio }
        assertEquals(15 + 3, lead)
        assertTrue(vad.speaking)
    }

    @Test
    fun `a click is not speech`() {
        val out = run(EnergyVad(), repeat(silence, 10) + repeat(tone(0.3), 2) + repeat(silence, 40))
        assertTrue(out.none { it.second is EnergyVad.Output.SpeechStart })
    }

    @Test
    fun `the end comes after 600 ms of quiet, stamped at the last loud frame, and the quiet is sent`() {
        val vad = EnergyVad()
        val out = run(vad, repeat(silence, 10) + repeat(tone(0.2), 25) + repeat(silence, 40))
        val end = out.first { it.second is EnergyVad.Output.SpeechEnd }
        // The voice ran from 200 ms to 700 ms (25 frames); quiet then lasted 600 ms.
        assertEquals(700.0, (end.second as EnergyVad.Output.SpeechEnd).at, 0.001)
        assertEquals(1280.0, end.first, 0.001)
        val sent = out.count { it.second is EnergyVad.Output.Audio }
        // The 10 quiet frames before (all there were of the 300 ms lead-in), the 25 loud ones,
        // and the 30 quiet frames of the hangover.
        assertEquals(10 + 25 + 30, sent)
        assertTrue(!vad.speaking)
        assertTrue(out.drop(out.indexOf(end) + 1).isEmpty())
    }

    @Test
    fun `a steady fan raises the threshold`() {
        val random = Random(7)
        val vad = EnergyVad()
        val fan = List(200) { noise(0.03, random) }
        val out = run(vad, fan)
        assertTrue(out.none { it.second is EnergyVad.Output.SpeechStart })
        // Speech well above the fan still counts.
        val speech = run(vad, repeat(tone(0.3), 10), start = 4_000.0)
        assertTrue(speech.any { it.second is EnergyVad.Output.SpeechStart })
    }

    @Test
    fun `while Ira speaks, her quieter echo does not interrupt, a voice over her does`() {
        val vad = EnergyVad()
        run(vad, repeat(silence, 20))
        vad.replying = true
        val echo = run(vad, repeat(tone(0.035), 30), start = 400.0)
        assertTrue(echo.none { it.second is EnergyVad.Output.SpeechStart })
        val voice = run(vad, repeat(tone(0.3), 10), start = 1_000.0)
        assertTrue(voice.any { it.second is EnergyVad.Output.SpeechStart })
    }

    @Test
    fun `speech is cut at a minute`() {
        val vad = EnergyVad()
        val out = run(vad, repeat(tone(0.2), 3_010))
        assertTrue(out.any { it.second is EnergyVad.Output.SpeechEnd })
    }

    @Test
    fun `pcm is little-endian`() {
        val bytes = Pcm.toBytes(shortArrayOf(1, -2, 0x1234))
        assertEquals(listOf(1, 0, -2, -1, 0x34, 0x12), bytes.map { it.toInt() })
        assertEquals(listOf<Short>(1, -2, 0x1234), Pcm.toSamples(bytes).toList())
    }
}
