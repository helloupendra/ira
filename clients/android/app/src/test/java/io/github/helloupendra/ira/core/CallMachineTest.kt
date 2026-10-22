package io.github.helloupendra.ira.core

import io.github.helloupendra.ira.core.CallMachine.Effect
import io.github.helloupendra.ira.core.CallMachine.Phase
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Turn-taking and barge-in, with no Android: what goes in, and what the app must do. */
class CallMachineTest {
    private fun sent(effects: List<Effect>) = effects.filterIsInstance<Effect.Send>().map { parseObject(it.json)!!.string("type") }

    private fun played(effects: List<Effect>) = effects.filterIsInstance<Effect.Play>().flatMap { it.sentences }.map { it.turn to it.seq }

    private fun CallMachine.audio(turn: Int, seq: Int): List<Effect> {
        onServer(Live.AudioHeader(turn, seq, "s", "mp3", 2), 0.0)
        return onBinary(byteArrayOf(1, 2))
    }

    private fun ready(): CallMachine {
        val m = CallMachine()
        m.onServer(Live.Ready(1, "c1", "Ira", listOf("hi-IN", "en-IN"), "polly"), 0.0)
        return m
    }

    @Test
    fun `a whole turn`() {
        val m = ready()
        assertEquals(Phase.Listening, m.phase)
        assertEquals("c1", m.conversationId)
        assertEquals(listOf("speech_start"), sent(m.onSpeechStart(100.0)))
        assertEquals(Phase.UserSpeaking, m.phase)
        assertEquals(listOf("speech_end"), sent(m.onSpeechEnd(900.0)))
        assertEquals(Phase.Thinking, m.phase)
        m.onServer(Live.Heard(1, "kiska call aaya tha?", "hi-IN"), 0.0)
        assertEquals(listOf(1 to 0), played(m.audio(1, 0)))
        val first = m.onSentenceStarted(1, 2_000.0)
        assertEquals("""{"type":"played","turn":1,"at":2000.0}""", (first.single() as Effect.Send).json)
        assertEquals(Phase.Speaking, m.phase)
        assertTrue(m.playing)
        assertEquals(listOf(1 to 1), played(m.audio(1, 1)))
        m.onSentenceFinished()
        // The second sentence starting is not a new `played`.
        assertTrue(m.onSentenceStarted(1, 2_500.0).isEmpty())
        m.onServer(Live.Done(1, "Rahul Sharma ka call tha.", 5), 0.0)
        m.onSentenceFinished()
        assertEquals(Phase.Listening, m.phase)
        assertTrue(!m.playing)
    }

    @Test
    fun `speaking over Ira stops her at once and drops the rest of her answer`() {
        val m = ready()
        m.onSpeechStart(0.0)
        m.onSpeechEnd(500.0)
        m.onServer(Live.Heard(1, "aaj ki khabar batao", "hi-IN"), 0.0)
        m.audio(1, 0)
        m.onSentenceStarted(1, 1_500.0)
        val barge = m.onSpeechStart(2_000.0)
        assertTrue(Effect.StopPlayback in barge)
        assertEquals(listOf("speech_start"), sent(barge))
        assertEquals(Phase.UserSpeaking, m.phase)
        assertTrue(!m.playing)
        // Sentences of the old answer still on their way are never played...
        assertTrue(played(m.audio(1, 1)).isEmpty())
        m.onServer(Live.Interrupted(1), 0.0)
        // ...but the next answer is.
        m.onSpeechEnd(2_800.0)
        m.onServer(Live.Heard(2, "ruko", "hi-IN"), 0.0)
        assertEquals(listOf(2 to 0), played(m.audio(2, 0)))
    }

    @Test
    fun `speaking while Ira is still thinking drops that answer too`() {
        val m = ready()
        m.onSpeechStart(0.0)
        m.onSpeechEnd(500.0)
        m.onServer(Live.Heard(1, "one", "en-IN"), 0.0)
        val barge = m.onSpeechStart(900.0)
        assertTrue(Effect.StopPlayback in barge)
        assertTrue(played(m.audio(1, 0)).isEmpty())
        assertTrue(m.onServer(Live.Action(1, ActionCard("a", "sms_send", "send", 2, true, 120)), 0.0).isEmpty())
    }

    @Test
    fun `the stop button interrupts`() {
        val m = ready()
        m.onServer(Live.Heard(1, "x", null), 0.0)
        m.audio(1, 0)
        m.onSentenceStarted(1, 10.0)
        val stop = m.stop()
        assertTrue(Effect.StopPlayback in stop)
        assertEquals(listOf("interrupt"), sent(stop))
        assertEquals(Phase.Listening, m.phase)
    }

    @Test
    fun `typing over Ira interrupts her first, then sends the text`() {
        val m = ready()
        m.onServer(Live.Heard(1, "x", null), 0.0)
        m.audio(1, 0)
        m.onSentenceStarted(1, 10.0)
        assertEquals(listOf("interrupt", "text"), sent(m.typed("  haan  ")))
        assertTrue(m.typed("   ").isEmpty())
    }

    @Test
    fun `typing while Ira listens is only text`() {
        val m = ready()
        assertEquals(listOf("text"), sent(m.typed("yes")))
        assertEquals(Phase.Thinking, m.phase)
    }

    @Test
    fun `the server's interruption stops playback`() {
        val m = ready()
        m.onServer(Live.Heard(1, "x", null), 0.0)
        m.audio(1, 0)
        m.onSentenceStarted(1, 10.0)
        assertTrue(Effect.StopPlayback in m.onServer(Live.Interrupted(1), 0.0))
        assertEquals(Phase.Listening, m.phase)
    }

    @Test
    fun `pings are answered, fatal errors end the call, others do not`() {
        val m = ready()
        assertEquals(listOf("pong"), sent(m.onServer(Live.Ping, 0.0)))
        m.onSpeechEnd(0.0)
        assertTrue(m.onServer(Live.Error("I didn't catch that.", false), 0.0).isEmpty())
        assertEquals(Phase.Listening, m.phase)
        assertEquals(Effect.End("no voice"), m.onServer(Live.Error("no voice", true), 0.0).single())
    }

    @Test
    fun `a proposed action is shown`() {
        val m = ready()
        val card = ActionCard("a1", "call_place", "call Rahul Sharma, +91 98100 00000", 2, true, 120)
        assertEquals(Effect.ShowAction(1, card), m.onServer(Live.Action(1, card), 0.0).single())
    }
}
