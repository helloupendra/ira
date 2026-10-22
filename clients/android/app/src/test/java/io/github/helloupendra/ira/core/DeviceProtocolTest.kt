package io.github.helloupendra.ira.core

import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DeviceProtocolTest {
    @Test
    fun `the hello says kind android and lists the tools with skill and tier`() {
        val tools = ToolCatalog.forFlavor(Flavor.PLAY)
        val hello = parseObject(DeviceProtocol.hello("Pixel 7", "0.1.0", tools))!!
        assertEquals("hello", hello.string("type"))
        assertEquals("android", hello.string("kind"))
        assertEquals("Pixel 7", hello.string("label"))
        assertEquals("0.1.0", hello.string("version"))
        val listed = hello["tools"]!!.jsonArray.map { it.jsonObject }
        assertEquals(tools.size, listed.size)
        val call = listed.first { it.string("name") == "call_place" }
        assertEquals("calls", call.string("skill"))
        assertEquals(2, call.int("tier"))
        assertEquals("object", call.obj("parameters")!!.string("type"))
    }

    @Test
    fun `both builds pass the server's hello rules`() {
        for (flavor in Flavor.entries) {
            assertEquals(emptyList<String>(), DeviceProtocol.problems(ToolCatalog.forFlavor(flavor)))
        }
    }

    @Test
    fun `the server's frames are understood`() {
        assertEquals(
            DeviceFrame.Welcome(3, "Pixel 7", listOf("calls"), "Ira", "Hey Ira"),
            DeviceProtocol.parse("""{"type": "welcome", "deviceId": 3, "label": "Pixel 7", "skills": ["calls"], "assistant": "Ira", "wakePhrase": "Hey Ira"}"""),
        )
        val call = DeviceProtocol.parse("""{"type": "call", "id": "9b0c", "tool": "calls_recent", "args": {"limit": 3}}""") as DeviceFrame.Call
        assertEquals("9b0c", call.id)
        assertEquals("calls_recent", call.tool)
        assertEquals(3, call.args.int("limit"))
        assertEquals(DeviceFrame.Skills(listOf("calls", "contacts")), DeviceProtocol.parse("""{"type": "skills", "skills": ["calls", "contacts"]}"""))
        assertEquals(DeviceFrame.Event("task_done", "Done", "The task finished."), DeviceProtocol.parse("""{"type": "event", "event": "task_done", "title": "Done", "text": "The task finished.", "at": 1.0}"""))
        assertEquals(DeviceFrame.Ping, DeviceProtocol.parse("""{"type": "ping"}"""))
        assertTrue(DeviceProtocol.parse("""{"type": "call", "tool": "x"}""") is DeviceFrame.Unknown)
        assertTrue(DeviceProtocol.parse("nope") is DeviceFrame.Unknown)
    }

    @Test
    fun `results carry the call's id`() {
        val ok = parseObject(DeviceProtocol.result("9b0c", buildJsonObject { put("summary", JsonPrimitive("2 calls")) }))!!
        assertEquals("9b0c", ok.string("id"))
        assertEquals(true, ok.bool("ok"))
        assertEquals("2 calls", ok.obj("content")!!.string("summary"))
        val bad = parseObject(DeviceProtocol.failure("9b0c", "x".repeat(900)))!!
        assertEquals(false, bad.bool("ok"))
        assertEquals(500, bad.string("error")!!.length)
    }
}

class ToolCatalogTest {
    private val play = ToolCatalog.forFlavor(Flavor.PLAY).associateBy { it.name }
    private val personal = ToolCatalog.forFlavor(Flavor.PERSONAL).associateBy { it.name }

    @Test
    fun `the owner's example has its three tools`() {
        for (name in listOf("calls_recent", "contacts_lookup", "call_place")) {
            assertTrue(name in play)
            assertTrue(name in personal)
        }
    }

    @Test
    fun `the Play build has no Accessibility tool`() {
        assertFalse(play.values.any { SpecialAccess.ACCESSIBILITY in it.special })
        assertFalse("screen_read" in play)
        assertFalse("screen_act" in play)
        assertTrue("screen_read" in personal)
        assertTrue("screen_act" in personal)
    }

    @Test
    fun `SMS and call-log tools are marked restricted, and only they`() {
        val restricted = play.values.filter { it.restricted }.map { it.name }.toSet()
        assertEquals(setOf("calls_recent", "sms_read", "sms_send"), restricted)
        val needing = play.values.filter { tool -> tool.permissions.any { it in setOf(Permissions.READ_CALL_LOG, Permissions.READ_SMS, Permissions.SEND_SMS) } }
        assertEquals(restricted, needing.map { it.name }.toSet())
    }

    @Test
    fun `tiers are 0 to read, 1 to open or play, 2 to call, send, reply or change the calendar, 3 for the screen`() {
        val tiers = personal.mapValues { it.value.tier }
        for (read in listOf("calls_recent", "contacts_lookup", "sms_read", "notifications_read", "calendar_read", "location_now")) assertEquals(read, 0, tiers[read])
        for (small in listOf("app_open", "maps_navigate", "media_control", "alarm_set", "timer_set", "reminder_set", "settings_toggle")) assertEquals(small, 1, tiers[small])
        for (outward in listOf("call_place", "sms_send", "notification_reply", "calendar_add")) assertEquals(outward, 2, tiers[outward])
        for (screen in listOf("screen_read", "screen_act")) assertEquals(screen, 3, tiers[screen])
    }

    @Test
    fun `skills are the server's names`() {
        val allowed = setOf("calls", "contacts", "messages", "notifications", "calendar", "reminders", "apps", "location", "media", "settings", "screen")
        assertTrue(personal.values.all { it.skill in allowed })
    }

    @Test
    fun `calls and sends name their exact target`() {
        for (name in listOf("call_place", "sms_send")) {
            val properties = personal.getValue(name).parameters["properties"]!!.jsonObject
            assertTrue("number" in properties && "name" in properties)
        }
        val required = personal.getValue("sms_send").parameters["required"]!!.jsonArray.map { it.jsonPrimitive.content }
        assertEquals(listOf("number", "text"), required)
    }

    @Test
    fun `location is coarse on Play and fine in the personal build`() {
        assertEquals(listOf(Permissions.COARSE_LOCATION), play.getValue("location_now").permissions)
        assertEquals(listOf(Permissions.FINE_LOCATION), personal.getValue("location_now").permissions)
    }
}
