package io.github.helloupendra.ira.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AudioAssemblerTest {
    private fun header(turn: Int, seq: Int, bytes: Int = 3) = Live.AudioHeader(turn, seq, "s$seq", "mp3", bytes)

    private fun mp3(n: Int = 3) = ByteArray(n) { it.toByte() }

    @Test
    fun `each header takes the binary frame after it`() {
        val a = AudioAssembler()
        a.onMessage(header(1, 0))
        val out = a.onBinary(mp3())
        assertEquals(listOf(1 to 0), out.map { it.turn to it.seq })
        assertEquals("s0", out[0].text)
        assertEquals(3, out[0].mp3.size)
    }

    @Test
    fun `sentences play in seq order even when they arrive out of order`() {
        val a = AudioAssembler()
        a.onMessage(header(2, 1))
        assertTrue(a.onBinary(mp3()).isEmpty())
        a.onMessage(header(2, 0))
        assertEquals(listOf(0, 1), a.onBinary(mp3()).map { it.seq })
        a.onMessage(header(2, 2))
        assertEquals(listOf(2), a.onBinary(mp3()).map { it.seq })
    }

    @Test
    fun `a binary frame with no header is dropped`() {
        val a = AudioAssembler()
        assertTrue(a.onBinary(mp3()).isEmpty())
        assertEquals(1, a.discarded)
    }

    @Test
    fun `a header followed by text loses its audio`() {
        val a = AudioAssembler()
        a.onMessage(header(1, 0))
        a.onMessage(Live.Delta(1, "x"))
        assertTrue(a.onBinary(mp3()).isEmpty())
        assertEquals(2, a.discarded)
    }

    @Test
    fun `a frame of the wrong size is dropped without stalling the next`() {
        val a = AudioAssembler()
        a.onMessage(header(1, 0, bytes = 10))
        assertTrue(a.onBinary(mp3(3)).isEmpty())
        a.onMessage(header(1, 1))
        assertEquals(listOf(1), a.onBinary(mp3()).map { it.seq })
    }

    @Test
    fun `audio of an interrupted turn is dropped, the next turn plays`() {
        val a = AudioAssembler()
        a.onMessage(header(3, 0))
        a.onBinary(mp3())
        a.onMessage(Live.Interrupted(3))
        a.onMessage(header(3, 1))
        assertTrue(a.onBinary(mp3()).isEmpty())
        a.onMessage(header(4, 0))
        assertEquals(listOf(4 to 0), a.onBinary(mp3()).map { it.turn to it.seq })
    }

    @Test
    fun `a barge-in drops the turns so far, even audio already on its way`() {
        val a = AudioAssembler()
        a.onMessage(header(5, 0))
        a.drop(5)
        assertTrue(a.onBinary(mp3()).isEmpty())
        assertEquals(5, a.droppedThrough)
    }

    @Test
    fun `a lost sentence is skipped once later ones pile up`() {
        val a = AudioAssembler()
        for (seq in 1..2) {
            a.onMessage(header(1, seq))
            assertTrue(a.onBinary(mp3()).isEmpty())
        }
        a.onMessage(header(1, 3))
        assertEquals(listOf(1, 2, 3), a.onBinary(mp3()).map { it.seq })
    }
}
