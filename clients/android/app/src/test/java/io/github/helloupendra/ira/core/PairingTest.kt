package io.github.helloupendra.ira.core

import java.io.IOException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class PairingTest {
    private val token = "irad_" + "x".repeat(43)

    private class Recorder(private val reply: () -> HttpReply) : HttpPost {
        var url = ""
        var body = ""
        var headers = emptyMap<String, String>()

        override fun post(url: String, body: String, headers: Map<String, String>): HttpReply {
            this.url = url
            this.body = body
            this.headers = headers
            return reply()
        }
    }

    @Test
    fun `a pasted link names its server and code`() {
        assertEquals("https://ira.example.com" to "ABCD-EFGH", Pairing.parse("https://ira.example.com/pair#code=ABCD-EFGH", null))
        assertEquals("https://ira.example.com/sub" to "ABCDEFGH", Pairing.parse("  https://ira.example.com/sub/pair#code=ABCDEFGH \n", "https://other.example.com"))
    }

    @Test
    fun `a typed code needs the server`() {
        assertEquals("https://ira.example.com" to "ABCD-EFGH", Pairing.parse("ABCD-EFGH", "https://ira.example.com/"))
        val error = assertThrows(PairError::class.java) { Pairing.parse("ABCD-EFGH", null) }
        assertEquals("say which server this code is for", error.message)
    }

    @Test
    fun `anything else is refused`() {
        for (entry in listOf("", "hello", "ABC", "https://ira.example.com/pair#code=AB", "ftp://ira.example.com/pair#code=ABCDEFGH")) {
            assertThrows(PairError::class.java) { Pairing.parse(entry, "https://ira.example.com") }
        }
    }

    @Test
    fun `http only to the phone itself`() {
        assertEquals("https://ira.example.com", Pairing.checkServer("https://ira.example.com/"))
        assertEquals("http://127.0.0.1:8000", Pairing.checkServer("http://127.0.0.1:8000"))
        assertEquals("http://localhost:8000", Pairing.checkServer("http://localhost:8000"))
        val error = assertThrows(PairError::class.java) { Pairing.checkServer("http://ira.example.com") }
        assertEquals("use https:// for a server on another machine", error.message)
        assertThrows(PairError::class.java) { Pairing.checkServer("ira.example.com") }
    }

    @Test
    fun `the request is the Mac companion's, as kind android, with the app's user agent`() {
        val post = Recorder { HttpReply(200, """{"device_id": 3, "token": "$token", "kind": "android", "label": "Pixel 7", "skills": ["calls"], "name": "Ira", "websocket": "/v1/devices/ws"}""") }
        val paired = Pairing.exchange("https://ira.example.com", "ABCD-EFGH", "0.1.0", post)
        assertEquals("https://ira.example.com/v1/devices/pair", post.url)
        assertEquals("""{"code":"ABCD-EFGH","kind":"android"}""", post.body)
        assertEquals("application/json", post.headers["Content-Type"])
        assertEquals("ira-android/0.1.0", post.headers["User-Agent"])
        assertEquals(3, paired.deviceId)
        assertEquals(token, paired.token)
        assertEquals("Pixel 7", paired.label)
        assertEquals(listOf("calls"), paired.skills)
        assertEquals("/v1/devices/ws", paired.websocket)
    }

    @Test
    fun `defaults when the answer leaves things out`() {
        val paired = Pairing.parseReply("https://ira.example.com", """{"device_id": 4, "token": "$token"}""")
        assertEquals("My Android phone", paired.label)
        assertEquals("Ira", paired.assistant)
        assertEquals("/v1/devices/ws", paired.websocket)
        assertTrue(paired.skills.isEmpty())
    }

    @Test
    fun `errors are said plainly`() {
        fun fails(reply: HttpReply) = assertThrows(PairError::class.java) { Pairing.exchange("https://ira.example.com", "ABCD-EFGH", "0.1.0") { _, _, _ -> reply } }.message

        assertEquals("that code is used, expired or mistyped; make a new one", fails(HttpReply(410, "")))
        assertEquals("too many wrong codes; wait 15 minutes", fails(HttpReply(429, "")))
        assertEquals("the server answered HTTP 502", fails(HttpReply(502, "")))
        assertEquals("https://ira.example.com did not answer like an Ira server", fails(HttpReply(200, "<html>")))
        assertEquals("the server's answer did not hold a device token", fails(HttpReply(200, """{"device_id": 1}""")))
        assertEquals("the server's answer did not hold a device token", fails(HttpReply(200, """{"token": "$token"}""")))
        val offline = assertThrows(PairError::class.java) { Pairing.exchange("https://ira.example.com", "ABCD-EFGH", "0.1.0") { _, _, _ -> throw IOException("timeout") } }
        assertEquals("could not reach https://ira.example.com: timeout", offline.message)
    }

    @Test
    fun `the token never shows in a printed pairing`() {
        val paired = Pairing.parseReply("https://ira.example.com", """{"device_id": 4, "token": "$token"}""")
        assertFalse(paired.toString().contains("irad_"))
    }

    @Test
    fun `websocket addresses follow the server's scheme`() {
        assertEquals("wss://ira.example.com/v1/voice/live", Pairing.websocketUrl("https://ira.example.com/", "/v1/voice/live"))
        assertEquals("ws://127.0.0.1:8000/v1/devices/ws", Pairing.websocketUrl("http://127.0.0.1:8000", "/v1/devices/ws"))
    }
}
