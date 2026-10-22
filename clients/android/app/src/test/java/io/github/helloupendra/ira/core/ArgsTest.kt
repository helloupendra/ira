package io.github.helloupendra.ira.core

import java.time.LocalDateTime
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class ArgsTest {
    private fun args(json: String) = Args(parseObject(json)!!)

    @Test
    fun `phone numbers keep digits and a leading plus`() {
        assertEquals("+919810000000", Args.phoneNumber("+91 98100 00000"))
        assertEquals("02212345678", Args.phoneNumber("(022) 1234-5678"))
        assertThrows(ToolFailure::class.java) { Args.phoneNumber("call Rahul") }
        assertThrows(ToolFailure::class.java) { Args.phoneNumber("12") }
        assertThrows(ToolFailure::class.java) { Args.phoneNumber("*21*123#") }
        assertEquals("9810000000", Args.numberKey("+91 98100 00000"))
    }

    @Test
    fun `numbers are checked`() {
        assertEquals(5, args("""{"limit": 5}""").int("limit", 1, 20, 10))
        assertEquals(10, args("""{}""").int("limit", 1, 20, 10))
        assertEquals(7, args("""{"limit": "7"}""").int("limit", 1, 20, 10))
        assertThrows(ToolFailure::class.java) { args("""{"limit": 99}""").int("limit", 1, 20) }
        assertThrows(ToolFailure::class.java) { args("""{"limit": 2.5}""").int("limit", 1, 20) }
        assertThrows(ToolFailure::class.java) { args("""{"limit": "many"}""").int("limit", 1, 20) }
        assertThrows(ToolFailure::class.java) { args("""{}""").requireInt("hour", 0, 23) }
    }

    @Test
    fun `text is checked`() {
        assertEquals("Rahul", args("""{"name": "  Rahul "}""").string("name", 80))
        assertNull(args("""{"name": ""}""").string("name", 80))
        assertThrows(ToolFailure::class.java) { args("""{}""").string("text", 10, required = true) }
        assertThrows(ToolFailure::class.java) { args("""{"text": 5}""").string("text", 10) }
        assertThrows(ToolFailure::class.java) { args("""{"text": "${"x".repeat(11)}"}""").string("text", 10) }
    }

    @Test
    fun `choices, lists and flags`() {
        assertEquals("missed", args("""{"kind": "Missed"}""").choice("kind", listOf("any", "missed")))
        assertThrows(ToolFailure::class.java) { args("""{"kind": "all"}""").choice("kind", listOf("any", "missed")) }
        assertEquals(listOf("mon", "fri"), args("""{"days": ["mon", "fri"]}""").list("days"))
        assertEquals(true, args("""{"all_day": true}""").bool("all_day"))
    }

    @Test
    fun `local times`() {
        assertEquals(LocalDateTime.of(2026, 10, 23, 9, 0), Args.localDateTime("2026-10-23T09:00"))
        assertEquals(LocalDateTime.of(2026, 10, 23, 9, 0), Args.localDateTime("2026-10-23 09:00"))
        assertThrows(ToolFailure::class.java) { Args.localDateTime("kal subah") }
        assertThrows(ToolFailure::class.java) { Args.localDate("23/10/2026") }
    }
}
