package io.github.helloupendra.ira.core

import java.time.Instant
import java.time.ZoneOffset
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NowTest {
    private val now = Instant.parse("2026-11-01T08:30:00Z")

    private fun item(createdAt: String) =
        Drop.Item(
            id = 7, kind = "file", text = null, name = "clinic-photo.png", mime = "image/png", size = 1200,
            sha256 = null, fromDeviceId = 2, fromLabel = "Pixel 7", createdAt = createdAt,
        )

    @Test
    fun `the newest drop of the last day and the devices that are on`() {
        val devices = Now.devices("""[{"id":1,"label":"MacBook","connected":true},{"id":2,"label":"Pixel 7","connected":true},{"id":3,"label":"Office PC","connected":false}]""")
        val cards = Now.cards(item("2026-11-01T08:15:00Z"), devices, now, ZoneOffset.UTC)
        assertEquals(listOf("Drop", "Devices"), cards.map { it.label })
        assertEquals("clinic-photo.png", cards[0].value)
        assertTrue(cards[0].detail.startsWith("from Pixel 7 · "))
        assertEquals(Now.Opens.DROP, cards[0].opens)
        assertEquals("MacBook · Pixel 7", cards[1].value)
        assertEquals("2 of 3 on", cards[1].detail)
    }

    @Test
    fun `nothing to show is no card, never filler`() {
        assertEquals(emptyList<Now.Card>(), Now.cards(item("2026-10-30T08:15:00Z"), emptyList(), now))
        assertEquals(emptyList<Now.Card>(), Now.cards(null, null, now))
        assertEquals("None connected", Now.cards(null, listOf(Now.Device("MacBook", false)), now).single().value)
    }

    @Test
    fun `a refusal or a page that is not a list gives no devices`() {
        assertNull(Now.devices("""{"detail":"missing permission"}"""))
        assertNull(Now.devices("not json"))
        assertEquals(listOf(Now.Device("MacBook", true)), Now.devices("""[{"label":"MacBook","connected":true},{"label":""}]"""))
    }

    @Test
    fun `the part of the day`() {
        assertEquals("morning", Now.partOfDay(9))
        assertEquals("afternoon", Now.partOfDay(13))
        assertEquals("evening", Now.partOfDay(19))
    }
}
