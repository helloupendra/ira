package io.github.helloupendra.ira.core

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TalkKeyTest {
    @Test
    fun `only the key from this process starts a call`() {
        assertTrue(TalkKey.matches(TalkKey.value))
        assertFalse(TalkKey.matches(null))
        assertFalse(TalkKey.matches(""))
        assertFalse(TalkKey.matches(TalkKey.value + "x"))
    }
}
