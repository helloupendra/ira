package io.github.helloupendra.ira.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ChecklistTest {
    private val fresh = Checklist.Facts(microphone = false, notifications = false, assistant = false, skillsOnServer = emptySet(), skillsWaitingOnPhone = emptySet())

    @Test
    fun `a new phone has every step to do, each with a button`() {
        val steps = Checklist.steps(fresh)
        assertEquals(5, steps.size)
        assertTrue(steps.none { it.done })
        assertTrue(steps.all { it.button.isNotBlank() })
        assertFalse(Checklist.complete(fresh))
    }

    @Test
    fun `before Android 13 there is no notification step`() {
        assertEquals(4, Checklist.steps(fresh.copy(notifications = null)).size)
    }

    @Test
    fun `skills on the server but not allowed on the phone are named`() {
        val facts = fresh.copy(skillsOnServer = setOf("calls", "contacts"), skillsWaitingOnPhone = setOf("contacts", "calls"))
        val step = Checklist.steps(facts).last()
        assertFalse(step.done)
        assertTrue(step.detail.endsWith("calls, contacts."))
    }

    @Test
    fun `all done`() {
        val facts = Checklist.Facts(true, true, true, setOf("calls"), emptySet())
        assertTrue(Checklist.complete(facts))
    }

    @Test
    fun `messages become sentences that say what to do`() {
        assertEquals("That code is used, expired or mistyped; make a new one.", Plain.sentence("that code is used, expired or mistyped; make a new one"))
        assertEquals(
            "Couldn't reach https://ira.example.com (timeout). Check the address, and that the phone is online.",
            Plain.sentence("could not reach https://ira.example.com: timeout"),
        )
        assertEquals("Something went wrong.", Plain.sentence(null))
        assertEquals("Try again?", Plain.sentence("Try again?"))
    }
}
