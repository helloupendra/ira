package io.github.helloupendra.ira.core

import kotlin.math.PI
import kotlin.math.sin
import kotlin.random.Random
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The silent-microphone check on 20 ms frames of 16 kHz audio. */
class MicSilenceTest {
    private val frame = 320
    private val zeros = ShortArray(frame)

    private fun tone(amplitude: Double) = ShortArray(frame) { (sin(2 * PI * 220 * it / 16_000) * amplitude * 32767).toInt().toShort() }

    /** Feed frames from [from] ms; the times at which [MicSilence.check] said the input is silent. */
    private fun run(silence: MicSilence, frames: List<ShortArray>, from: Double = 0.0): List<Double> {
        val told = ArrayList<Double>()
        frames.forEachIndexed { i, f ->
            val end = from + i * 20.0 + 20.0
            silence.feed(f)
            if (silence.check(end)) told += end
        }
        return told
    }

    @Test
    fun `zeros for three seconds are said once`() {
        val silence = MicSilence()
        silence.start(0.0)
        assertEquals(listOf(3000.0), run(silence, List(250) { zeros }))
        assertTrue(silence.silent)
    }

    @Test
    fun `no frames at all is silent too`() {
        val silence = MicSilence()
        silence.start(1000.0)
        assertEquals(listOf(false, true, false), listOf(3990.0, 4000.0, 5000.0).map { silence.check(it) })
    }

    @Test
    fun `a quiet room is not silent`() {
        val silence = MicSilence()
        val random = Random(7)
        silence.start(0.0)
        // About -66 dBFS of noise: a quiet room through the phone's noise suppressor.
        val room = List(250) { ShortArray(frame) { ((random.nextDouble() * 2 - 1) * 0.0005 * 32767).toInt().toShort() } }
        assertEquals(emptyList<Double>(), run(silence, room))
        assertFalse(silence.silent)
    }

    @Test
    fun `sound after the warning clears it, and a new listen watches again`() {
        val silence = MicSilence()
        silence.start(0.0)
        assertEquals(listOf(3000.0), run(silence, List(160) { zeros }))
        silence.feed(tone(0.1))
        assertFalse(silence.silent)
        assertFalse(silence.check(9000.0))
        silence.start(10_000.0)
        assertTrue(silence.check(13_000.0))
        silence.reset()
        assertFalse(silence.check(20_000.0))
        assertFalse(silence.silent)
    }

    @Test
    fun `nothing is watched before listening`() {
        val silence = MicSilence()
        silence.feed(zeros)
        assertFalse(silence.check(60_000.0))
    }
}
