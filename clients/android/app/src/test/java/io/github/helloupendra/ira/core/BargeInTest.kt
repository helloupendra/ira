package io.github.helloupendra.ira.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** A sound while Ira speaks: the person (it stays loud with her turned down), or her echo. */
class BargeInTest {
    private val started = listOf(EnergyVad.Output.SpeechStart(1000.0), EnergyVad.Output.Audio(byteArrayOf(1, 2)))
    private val frame = listOf(EnergyVad.Output.Audio(byteArrayOf(3)))

    @Test
    fun `her echo fades when she is turned down, and nothing is sent`() {
        val barge = BargeIn()
        assertTrue(barge.feed(emptyList(), false, 980.0).isEmpty())
        assertEquals(listOf(BargeIn.Step.Duck), barge.feed(started, true, 1000.0))
        assertTrue(barge.checking)
        val steps = (1..16).flatMap { barge.feed(frame, it % 4 == 0, 1000.0 + it * 20) }
        assertEquals(listOf(BargeIn.Step.Release), steps)
        assertTrue(!barge.checking)
    }

    @Test
    fun `the person stays loud, and their speech goes on with nothing lost`() {
        val barge = BargeIn()
        barge.feed(started, true, 1000.0)
        val steps = (1..16).flatMap { barge.feed(frame, true, 1000.0 + it * 20) }
        assertEquals(1, steps.size)
        val held = (steps[0] as BargeIn.Step.Confirm).held
        assertTrue(held.first() is EnergyVad.Output.SpeechStart)
        assertEquals(2 + 15, held.size)
    }

    @Test
    fun `a sound over before it is checked is not the person`() {
        val barge = BargeIn()
        barge.feed(started, true, 1000.0)
        val end = listOf(EnergyVad.Output.Audio(byteArrayOf()), EnergyVad.Output.SpeechEnd(1100.0))
        assertEquals(listOf(BargeIn.Step.Release), barge.feed(end, false, 1100.0))
    }
}
