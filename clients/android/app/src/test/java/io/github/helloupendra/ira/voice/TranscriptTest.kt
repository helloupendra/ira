package io.github.helloupendra.ira.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class TranscriptTest {
    @Test
    fun `a second call's first answer is a new line, not the first call's`() {
        val transcript = Transcript()
        val first = LiveSession.lineKey(call = 1, generation = 1, turn = 1)
        transcript.add(Transcript.Line("$first:you", false, "Mac par kaun sa session chal raha hai?"))
        transcript.ira(first) { it.copy(text = "Two sessions are running.") }

        // The next call connects for the first time too, and its turns start at 1 again.
        val second = LiveSession.lineKey(call = 2, generation = 1, turn = 1)
        assertNotEquals(first, second)
        transcript.add(Transcript.Line("$second:you", false, "Kal ki appointment kab hai?"))
        transcript.ira(second) { it.copy(text = it.text + "Your appointment is at") }
        transcript.ira(second) { it.copy(text = it.text + " 10:30 tomorrow.") }

        val lines = transcript.lines.value
        assertEquals(4, lines.size)
        assertEquals("Two sessions are running.", lines[1].text)
        assertEquals("Your appointment is at 10:30 tomorrow.", lines.last { it.fromIra }.text)
    }

    @Test
    fun `a reconnect within a call keeps its lines apart too`() {
        assertNotEquals(LiveSession.lineKey(1, 1, 1), LiveSession.lineKey(1, 2, 1))
    }
}
