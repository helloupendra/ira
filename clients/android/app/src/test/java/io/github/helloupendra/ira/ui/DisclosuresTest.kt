package io.github.helloupendra.ira.ui

import io.github.helloupendra.ira.core.Skills
import io.github.helloupendra.ira.core.SpecialAccess
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DisclosuresTest {
    @Test
    fun `notification access and Accessibility show their skill's disclosure first`() {
        // Notification access sends what others wrote to the server: Play's prominent
        // disclosure comes before Android's settings page, not a line about which page opens.
        assertTrue(Disclosures.firstFor(SpecialAccess.NOTIFICATION_LISTENER))
        assertTrue(Disclosures.firstFor(SpecialAccess.ACCESSIBILITY))
        assertFalse(Disclosures.firstFor(SpecialAccess.EXACT_ALARMS))
        assertFalse(Disclosures.firstFor(SpecialAccess.DO_NOT_DISTURB))
        val text = Disclosures.skill(Skills.NOTIFICATIONS, "https://ira.example.com")
        assertNotNull(text)
        assertTrue(text!!.contains("https://ira.example.com"))
    }
}
