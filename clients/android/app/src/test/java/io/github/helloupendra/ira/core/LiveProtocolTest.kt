package io.github.helloupendra.ira.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LiveProtocolTest {
    @Test
    fun `client messages are protocol 1's`() {
        assertEquals("""{"type":"start","protocol":1,"client":"ira-android/0.1.0"}""", LiveProtocol.start("ira-android/0.1.0", null))
        assertEquals(
            """{"type":"start","protocol":1,"client":"ira-android/0.1.0","conversation_id":"a1b2c3"}""",
            LiveProtocol.start("ira-android/0.1.0", "a1b2c3"),
        )
        assertEquals("""{"type":"speech_start","at":1234.6}""", LiveProtocol.speechStart(1234.56))
        assertEquals("""{"type":"speech_end","at":2345.0}""", LiveProtocol.speechEnd(2345.0))
        assertEquals("""{"type":"text","text":"kal subah 9 baje yaad dilana"}""", LiveProtocol.text("kal subah 9 baje yaad dilana"))
        assertEquals("""{"type":"interrupt"}""", LiveProtocol.interrupt())
        assertEquals("""{"type":"played","turn":3,"at":3012.0}""", LiveProtocol.played(3, 3012.0))
        assertEquals("""{"type":"pong"}""", LiveProtocol.pong())
        assertEquals("""{"type":"bye"}""", LiveProtocol.bye())
    }

    @Test
    fun `quotes and Devanagari survive the framing`() {
        val text = "\"haan\" कल सुबह"
        val parsed = parseObject(LiveProtocol.text(text))!!
        assertEquals(text, parsed.string("text"))
    }

    @Test
    fun `every server message is understood`() {
        assertEquals(
            Live.Ready(1, "c1", "Ira", listOf("hi-IN", "en-IN"), "polly"),
            LiveProtocol.parse("""{"type": "ready", "protocol": 1, "conversation_id": "c1", "assistant": "Ira", "languages": ["hi-IN", "en-IN"], "tts": "polly"}"""),
        )
        assertEquals(Live.Partial("kal subah", "hi-IN"), LiveProtocol.parse("""{"type": "partial", "text": "kal subah", "language": "hi-IN"}"""))
        assertEquals(Live.Heard(3, "kiska call aaya tha?", "hi-IN"), LiveProtocol.parse("""{"type": "heard", "turn": 3, "text": "kiska call aaya tha?", "language": "hi-IN"}"""))
        assertEquals(Live.Delta(3, "Rahul"), LiveProtocol.parse("""{"type": "delta", "turn": 3, "text": "Rahul"}"""))
        assertEquals(
            Live.AudioHeader(3, 0, "Theek hai.", "mp3", 5321),
            LiveProtocol.parse("""{"type": "audio", "turn": 3, "seq": 0, "text": "Theek hai.", "format": "mp3", "bytes": 5321}"""),
        )
        assertEquals(Live.Done(3, "Done.", 812), LiveProtocol.parse("""{"type": "done", "turn": 3, "text": "Done.", "message_id": 812, "timings": {"stt_ms": 240}}"""))
        assertEquals(Live.Interrupted(3), LiveProtocol.parse("""{"type": "interrupted", "turn": 3}"""))
        assertEquals(Live.Ping, LiveProtocol.parse("""{"type": "ping"}"""))
        assertEquals(Live.Error("I didn't catch that. Say it again?", false), LiveProtocol.parse("""{"type": "error", "message": "I didn't catch that. Say it again?", "fatal": false}"""))
        assertEquals(Live.Error("no voice", true), LiveProtocol.parse("""{"type": "error", "message": "no voice", "fatal": true}"""))
    }

    @Test
    fun `an action carries its card`() {
        val parsed =
            LiveProtocol.parse(
                """{"type": "action", "turn": 4, "action": {"id": "a9", "tool": "call_place", "summary": "call number on Pixel 7: name Rahul Sharma, number +91 98100 00000", "status": "pending", "expires_in": 120, "tier": 2, "can_approve": true}}""",
            ) as Live.Action
        assertEquals(4, parsed.turn)
        assertEquals("a9", parsed.card.id)
        assertEquals(2, parsed.card.tier)
        assertTrue(parsed.card.canApprove)
        assertEquals(120, parsed.card.expiresIn)
        assertEquals(false, parsed.card.needsPin)
    }

    @Test
    fun `broken and unknown frames are not trusted`() {
        assertTrue(LiveProtocol.parse("not json") is Live.Unknown)
        assertTrue(LiveProtocol.parse("[1, 2]") is Live.Unknown)
        assertTrue(LiveProtocol.parse("""{"type": "surprise"}""") is Live.Unknown)
        assertTrue(LiveProtocol.parse("""{"no": "type"}""") is Live.Unknown)
    }

    @Test
    fun `audio goes up in frames of 640 to 3200 bytes, whole samples`() {
        val chunks = LiveProtocol.chunks(ByteArray(8_000))
        assertEquals(listOf(3_200, 3_200, 1_600), chunks.map { it.size })
        assertEquals(listOf(640), LiveProtocol.chunks(ByteArray(640)).map { it.size })
        assertTrue(LiveProtocol.chunks(ByteArray(10_000), 640).all { it.size == 640 || it.size == 10_000 % 640 })
    }
}
