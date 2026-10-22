package io.github.helloupendra.ira.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AskStreamTest {
    @Test
    fun `the request continues the conversation`() {
        assertEquals("""{"text":"mere phone par kaunse tools hain?","conversation_id":"c1"}""", AskStream.body("mere phone par kaunse tools hain?", "c1"))
        assertEquals("""{"text":"hi"}""", AskStream.body("hi", null))
    }

    @Test
    fun `server-sent events become events, other lines are skipped`() {
        assertEquals(AskStream.Event.Start("c1"), AskStream.parseLine("""data: {"type": "start", "conversation_id": "c1"}"""))
        assertEquals(AskStream.Event.Tool("calls_recent"), AskStream.parseLine("""data: {"type": "tool", "id": "t1", "name": "calls_recent", "arguments": {}}"""))
        assertEquals(AskStream.Event.Delta("Rahul"), AskStream.parseLine("""data:{"type": "delta", "text": "Rahul"}"""))
        assertEquals(AskStream.Event.Error("no model could answer"), AskStream.parseLine("""data: {"type": "error"}"""))
        assertEquals(
            AskStream.Event.Done("Rahul Sharma ka call tha.", "c1", 812),
            AskStream.parseLine("""data: {"type": "done", "text": "Rahul Sharma ka call tha.", "model": "demo:router", "conversation_id": "c1", "message_id": 812}"""),
        )
        val action = AskStream.parseLine("""data: {"type": "action", "action": {"id": "a1", "tool": "call_place", "summary": "call Rahul", "tier": 2, "can_approve": true}}""")
        assertTrue(action is AskStream.Event.Action && action.card.tier == 2)
        for (line in listOf("", ": keepalive", "event: message", "data: not json", """data: {"type": "tool_result"}""")) {
            assertNull(line, AskStream.parseLine(line))
        }
    }

    @Test
    fun `failures say what to do`() {
        assertTrue(AskStream.failure(401).contains("Pair it again"))
        assertTrue(AskStream.failure(429).contains("busy"))
        assertTrue(AskStream.failure(502).contains("Send it again"))
    }

    @Test
    fun `info says whether live calls work and who speaks`() {
        val info = ServerInfo.parse("""{"name": "Ira", "version": "0.3", "stt": null, "tts": null, "browser_stt": "fallback", "live": false, "mic_language": "hi-IN", "tools": [], "user": {}, "permissions": []}""")!!
        assertEquals(false, info.live)
        assertNull(info.tts)
        assertEquals("hi-IN", info.micLanguage)
        val live = ServerInfo.parse("""{"name": "Ira", "live": true, "tts": "polly", "mic_language": "xx"}""")!!
        assertTrue(live.live)
        assertEquals("polly", live.tts)
        assertEquals("en-IN", live.micLanguage)
        assertNull(ServerInfo.parse("<html>"))
    }
}
