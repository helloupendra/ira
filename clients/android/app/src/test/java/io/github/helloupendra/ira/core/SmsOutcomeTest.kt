package io.github.helloupendra.ira.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SmsOutcomeTest {
    @Test
    fun `an SMS is sent only when the phone says every part went`() {
        assertTrue(SmsOutcome.sent(listOf(SmsOutcome.OK, SmsOutcome.OK)))
        assertNull(SmsOutcome.failure(listOf(SmsOutcome.OK)))
        assertFalse(SmsOutcome.sent(listOf(SmsOutcome.OK, null))) // one part not confirmed in time
        assertNull(SmsOutcome.failure(listOf(SmsOutcome.OK, null)))
        assertFalse(SmsOutcome.sent(emptyList()))
    }

    @Test
    fun `a radio failure is never reported as sent`() {
        assertEquals("the phone's mobile radio is off (flight mode?)", SmsOutcome.failure(listOf(SmsOutcome.OK, 2)))
        assertEquals("there is no mobile service", SmsOutcome.failure(listOf(4)))
        assertEquals("the phone reported error 9", SmsOutcome.failure(listOf(null, 9)))
        assertFalse(SmsOutcome.sent(listOf(1)))
    }
}
