package io.github.helloupendra.ira.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ToolGateTest {
    private val everything = ToolCatalog.forFlavor(Flavor.PERSONAL).flatMap { it.permissions + it.optionalPermissions }.toSet()

    private fun state(flavor: Flavor, role: Boolean = true, call: Boolean = true, granted: Set<String> = everything, special: Set<SpecialAccess> = SpecialAccess.entries.toSet()) =
        ToolGate.State(flavor, role, call, granted, special)

    private fun tool(flavor: Flavor, name: String) = ToolCatalog.forFlavor(flavor).first { it.name == name }

    @Test
    fun `on Play, the call log needs the assistant role and a call on the phone`() {
        val calls = tool(Flavor.PLAY, "calls_recent")
        assertTrue(ToolGate.check(calls, state(Flavor.PLAY, role = false))!!.contains("digital assistant"))
        assertTrue(ToolGate.check(calls, state(Flavor.PLAY, call = false))!!.contains("while you talk to Ira"))
        assertNull(ToolGate.check(calls, state(Flavor.PLAY)))
    }

    @Test
    fun `the personal build needs neither`() {
        assertNull(ToolGate.check(tool(Flavor.PERSONAL, "sms_read"), state(Flavor.PERSONAL, role = false, call = false)))
    }

    @Test
    fun `unrestricted tools never need the role`() {
        assertNull(ToolGate.check(tool(Flavor.PLAY, "contacts_lookup"), state(Flavor.PLAY, role = false, call = false)))
    }

    @Test
    fun `a missing permission is named in plain words`() {
        val message = ToolGate.check(tool(Flavor.PLAY, "contacts_lookup"), state(Flavor.PLAY, granted = emptySet()))
        assertEquals("the phone has not allowed contacts yet: open Ira on the phone, Skills, and allow it", message)
    }

    @Test
    fun `an optional permission is not required`() {
        val granted = everything - Permissions.READ_CONTACTS
        assertNull(ToolGate.check(tool(Flavor.PERSONAL, "calls_recent"), state(Flavor.PERSONAL, granted = granted)))
    }

    @Test
    fun `special access is checked`() {
        val message = ToolGate.check(tool(Flavor.PLAY, "notifications_read"), state(Flavor.PLAY, special = emptySet()))
        assertTrue(message!!.startsWith("Notification access is off"))
    }

    @Test
    fun `a tool of the other build is refused`() {
        val screen = tool(Flavor.PERSONAL, "screen_read")
        assertEquals("this build of the app does not have screen_read", ToolGate.check(screen, state(Flavor.PLAY)))
    }
}
