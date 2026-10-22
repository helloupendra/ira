package io.github.helloupendra.ira.core

import java.io.IOException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ActionsTest {
    @Test
    fun `the PIN goes to the confirm endpoint with the device token`() {
        var seen = ""
        var headers = emptyMap<String, String>()
        var body = ""
        val outcome =
            Actions.confirm("https://ira.example.com/", "irad_x", "a1b2", "482916") { url, b, h ->
                seen = url
                body = b
                headers = h
                HttpReply(200, """{"status": "executed", "message": "Sent."}""")
            }
        assertEquals("https://ira.example.com/v1/actions/a1b2/confirm", seen)
        assertEquals("""{"pin":"482916"}""", body)
        assertEquals("Bearer irad_x", headers["Authorization"])
        assertEquals(Actions.Outcome("executed", "Sent.", true), outcome)
    }

    @Test
    fun `outcomes say what to do next`() {
        assertTrue(Actions.parse(HttpReply(403, """{"status": "wrong_pin", "attempts_left": 2}""")).message.contains("2 tries left"))
        assertTrue(Actions.parse(HttpReply(423, """{"status": "locked", "locked_seconds": 600}""")).message.contains("10 min"))
        assertTrue(Actions.parse(HttpReply(409, """{"status": "no_pin"}""")).message.contains("Set an action PIN"))
        assertTrue(Actions.parse(HttpReply(410, """{"status": "expired"}""")).message.contains("Ask Ira again"))
        assertTrue(Actions.parse(HttpReply(401, "")).message.contains("Pair it again"))
    }

    @Test
    fun `an odd action id or no network is handled`() {
        assertEquals("bad", Actions.confirm("https://ira.example.com", "t", "../admin", "1234") { _, _, _ -> HttpReply(200, "{}") }.status)
        assertEquals("offline", Actions.confirm("https://ira.example.com", "t", "a1", "1234") { _, _, _ -> throw IOException("down") }.status)
    }
}
