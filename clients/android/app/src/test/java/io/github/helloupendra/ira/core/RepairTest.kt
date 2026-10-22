package io.github.helloupendra.ira.core

import java.io.IOException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RepairTest {
    private val oldToken = "irad_old"
    private val newToken = "irad_new"

    private fun holder() = Holder("http://127.0.0.1:8820", oldToken)

    private class Holder(override var server: String?, override var token: String?) : Repair.Holder {
        val log = ArrayList<String>()
        override val websocketPath = "/v1/devices/ws"

        override fun replace(paired: Paired) {
            log += "replace"
            server = paired.server
            token = paired.token
        }
    }

    private val ok = HttpPost { _, _, _ -> HttpReply(200, """{"device_id": 3, "token": "$newToken", "label": "Pixel 7"}""") }

    @Test
    fun `a failed new pairing keeps the current one and tells nobody`() {
        for (post in listOf(HttpPost { _, _, _ -> HttpReply(410, "") }, HttpPost { _, _, _ -> throw IOException("down") }, HttpPost { _, _, _ -> HttpReply(200, "<html>") })) {
            val holder = holder()
            var told = false
            val result = Repair.run("https://ira.example.com/pair#code=ABCD-EFGH", null, "0.1.0", post, removeOld = true, holder = holder) { _, _, _ -> told = true }
            assertTrue(result is Repair.Result.Kept)
            assertEquals("http://127.0.0.1:8820", holder.server)
            assertEquals(oldToken, holder.token)
            assertTrue(holder.log.isEmpty())
            assertFalse(told)
        }
    }

    @Test
    fun `the new pairing replaces the old only after it worked, and the old server is not told`() {
        val holder = holder()
        var told = false
        val result = Repair.run("https://ira.example.com/pair#code=ABCD-EFGH", null, "0.1.0", ok, removeOld = false, holder = holder) { _, _, _ -> told = true }
        assertTrue(result is Repair.Result.Paired && !result.forgotOld)
        assertEquals("https://ira.example.com", holder.server)
        assertEquals(newToken, holder.token)
        assertFalse(told)
    }

    @Test
    fun `with the box ticked, the old server is told after the switch, with the old token`() {
        val holder = holder()
        val farewells = ArrayList<String>()
        val result =
            Repair.run("ABCD-EFGH", "https://ira.example.com", "0.1.0", ok, removeOld = true, holder = holder) { server, path, token ->
                farewells += "$server $path $token after ${holder.log.size} swap"
            }
        assertTrue(result is Repair.Result.Paired && result.forgotOld)
        assertEquals(listOf("http://127.0.0.1:8820 /v1/devices/ws $oldToken after 1 swap"), farewells)
    }

    @Test
    fun `a phone never paired before simply pairs`() {
        val holder = Holder(null, null)
        var told = false
        val result = Repair.run("https://ira.example.com/pair#code=ABCD-EFGH", null, "0.1.0", ok, removeOld = true, holder = holder) { _, _, _ -> told = true }
        assertTrue(result is Repair.Result.Paired)
        assertFalse(told)
    }

    @Test
    fun `a bad entry is said plainly and changes nothing`() {
        val holder = holder()
        val result = Repair.run("hello", null, "0.1.0", ok, removeOld = false, holder = holder) { _, _, _ -> }
        assertEquals(Repair.Result.Kept("Paste the pairing link or type the 8-character code."), result)
        assertEquals(oldToken, holder.token)
    }
}
