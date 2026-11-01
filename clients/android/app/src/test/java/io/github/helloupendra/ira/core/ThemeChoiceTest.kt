package io.github.helloupendra.ira.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ThemeChoiceTest {
    @Test
    fun `System follows the phone, Light and Dark do not`() {
        assertTrue(ThemeChoice.SYSTEM.dark(phoneDark = true))
        assertFalse(ThemeChoice.SYSTEM.dark(phoneDark = false))
        assertFalse(ThemeChoice.LIGHT.dark(phoneDark = true))
        assertTrue(ThemeChoice.DARK.dark(phoneDark = false))
    }

    @Test
    fun `a stored name reads back, and anything else is System`() {
        for (choice in ThemeChoice.entries) assertEquals(choice, ThemeChoice.from(choice.name))
        assertEquals(ThemeChoice.SYSTEM, ThemeChoice.from(null))
        assertEquals(ThemeChoice.SYSTEM, ThemeChoice.from("sepia"))
    }

    @Test
    fun `the choices read System, Light, Dark in that order`() {
        assertEquals(listOf("System", "Light", "Dark"), ThemeChoice.entries.map { it.label })
    }
}
