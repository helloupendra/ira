package io.github.helloupendra.ira.core

import java.io.IOException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ReportsTest {
    @Test
    fun `a report goes to the reports route with the device token`() {
        var url = ""
        var body = ""
        var headers = emptyMap<String, String>()
        val result =
            Reports.send("https://ira.example.com/", "irad_x", 812, "wrong", "  the  time \n was wrong ") { u, b, h ->
                url = u
                body = b
                headers = h
                HttpReply(200, """{"id": "rep_1a2b", "status": "open"}""")
            }
        assertEquals("https://ira.example.com/v1/me/reports", url)
        assertEquals("""{"message_id":812,"reason":"wrong","note":"the time was wrong"}""", body)
        assertEquals("Bearer irad_x", headers["Authorization"])
        assertEquals("application/json", headers["Content-Type"])
        assertTrue(result.ok)
        assertTrue(result.message.startsWith("Thanks, reported"))
    }

    @Test
    fun `the note is optional and capped`() {
        assertEquals("""{"message_id":5,"reason":"other"}""", Reports.body(5, "other", "   "))
        val long = Reports.body(5, "other", "x".repeat(900))
        assertEquals(Reports.MAX_NOTE, parseObject(long)!!.string("note")!!.length)
    }

    @Test
    fun `every reason is one the server knows`() {
        assertEquals(listOf("wrong", "harmful", "offensive", "private", "other"), Reports.REASONS.map { it.first })
    }

    @Test
    fun `errors say what to do next`() {
        fun fails(reply: HttpReply) = Reports.parse(reply).also { assertFalse(it.ok) }.message

        assertTrue(fails(HttpReply(404, """{"detail": "no such answer"}""")).contains("no longer in your conversations"))
        assertTrue(fails(HttpReply(422, "{}")).contains("Update the app"))
        assertTrue(fails(HttpReply(401, "")).contains("Pair it again"))
        assertTrue(fails(HttpReply(403, "")).contains("Pair it again"))
        assertTrue(fails(HttpReply(500, "")).contains("HTTP 500"))
        assertTrue(fails(HttpReply(200, "<html>")).contains("Try again later"))
    }

    @Test
    fun `nothing is sent without an answer, a reason or a network`() {
        var sent = false
        val poster = HttpPost { _, _, _ -> sent = true; HttpReply(200, """{"id": "r"}""") }
        assertFalse(Reports.send("https://ira.example.com", "t", 0, "wrong", null, poster).ok)
        assertFalse(Reports.send("https://ira.example.com", "t", 3, "rude", null, poster).ok)
        assertFalse(sent)
        val offline = Reports.send("https://ira.example.com", "t", 3, "wrong", null) { _, _, _ -> throw IOException("down") }
        assertTrue(offline.message.startsWith("Could not reach your Ira"))
    }
}
