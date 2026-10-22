package io.github.helloupendra.ira.core

import java.security.KeyPairGenerator
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ApprovalsTest {
    @Test
    fun `a window covers screen and app control, never the never-list`() {
        for (tool in listOf("screen_read", "screen_act", "app_open", "url_open", "media_play", "media_control", "settings_toggle")) {
            assertTrue(tool, Approvals.covered(tool))
        }
        for (tool in listOf("sms_send", "call_place", "notification_reply", "calendar_add", "calls_recent", "reminder_set")) {
            assertFalse(tool, Approvals.covered(tool))
        }
    }

    @Test
    fun `the server's window list is read, and this phone's open window found`() {
        val status =
            Approvals.Status.parse(
                """{"minutes": 15, "windows": [
                    {"id": "apw_1", "device_id": 3, "device": "Pixel 7", "opened_at": 1000.0, "expires_at": 1900.0, "steps": 4},
                    {"id": "apw_2", "device_id": 5, "device": "Office Mac", "opened_at": 1000.0, "expires_at": 2000.0, "steps": 1},
                    {"id": "apw_0", "device_id": 3, "device": "Pixel 7", "opened_at": 100.0, "expires_at": 900.0, "steps": 2}
                ]}""",
            )!!
        assertEquals(15, status.minutes)
        assertEquals(3, status.windows.size)
        val mine = status.forDevice(3, now = 1180.0)!!
        assertEquals("apw_1", mine.id)
        assertEquals(720L, mine.secondsLeft(1180.0))
        assertNull(status.forDevice(3, now = 1900.0))
        assertNull(Approvals.Status.parse("<html>"))
        assertEquals(0, Approvals.Status.parse("""{"minutes": 0, "windows": []}""")!!.windows.size)
    }

    @Test
    fun `the banner counts down, in the server's words`() {
        assertEquals("Ira can use this phone for 12 more minutes", Approvals.banner(11 * 60 + 1))
        assertEquals("Ira can use this phone for 1 more minute", Approvals.banner(60))
        assertEquals("Ira can use this phone for less than a minute more", Approvals.banner(30))
        assertNull(Approvals.banner(0))
    }

    @Test
    fun `stopping a window names it safely`() {
        assertEquals("/v1/me/approvals/apw_1", Approvals.windowPath("apw_1"))
        assertNull(Approvals.windowPath("../keys"))
    }

    // The device key, against docs/security.md "Approving with the device's own key".

    @Test
    fun `the signed bytes are the spec's, line by line`() {
        val payload = Approvals.payload("act_1f2e3d4c", "screen_act on Pixel 7: tap Search in YouTube", 1_792_700_000)
        assertEquals(
            "ira-approve:1\nact_1f2e3d4c\n20428fbe66d7aeba86ceca1f9ab05c5c45dfaa2f2a43db7524898df061d74efb\n1792700000",
            String(payload, Charsets.UTF_8),
        )
        assertThrows(IllegalArgumentException::class.java) { Approvals.payload("act\n2", "x", 1) }
    }

    @Test
    fun `a fixed test vector verifies - a key and a signature made once, for the server to check too`() {
        // A public key and a signature, not secrets: the scanner only sees long base64.
        val publicKey =
            "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEzEeDdkb2G9ueJbSbivYighO9a4ZMeA6AuPjYp4SVU9vXVU3PPhii9QOhEcRkwwc+YmA1ORqYn2V1KmxXmX/AIg==" // pragma: allowlist secret
        val signature = "MEQCIAWZQdxTD8irjk1oIIR9mFTAn3pO_kIrONqUH-doStBeAiB4Nz7EdM49Fv_bkWDjCWQCf6LNPKwDEgn6ELSUSrBuVQ" // pragma: allowlist secret
        val payload = Approvals.payload("act_1f2e3d4c", "screen_act on Pixel 7: tap Search in YouTube", 1_792_700_000)
        assertTrue(Approvals.verify(publicKey, payload, signature))
        // Any change to what was shown, the action or the expiry breaks it.
        assertFalse(Approvals.verify(publicKey, Approvals.payload("act_1f2e3d4c", "screen_act on Pixel 7: tap Subscribe", 1_792_700_000), signature))
        assertFalse(Approvals.verify(publicKey, Approvals.payload("act_other", "screen_act on Pixel 7: tap Search in YouTube", 1_792_700_000), signature))
        assertFalse(Approvals.verify(publicKey, Approvals.payload("act_1f2e3d4c", "screen_act on Pixel 7: tap Search in YouTube", 1_792_700_001), signature))
    }

    @Test
    fun `a key like the Keystore's signs and verifies in the spec's encodings`() {
        val keys = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
        val payload = Approvals.payload("act_9", "url_open on Pixel 7: https://www.youtube.com/", 1_792_700_000)
        val signature =
            Approvals.base64url(Signature.getInstance(Approvals.SIGNATURE_ALGORITHM).run {
                initSign(keys.private)
                update(payload)
                sign()
            })
        assertFalse(signature.contains('=') || signature.contains('+') || signature.contains('/'))
        assertTrue(Approvals.verify(Approvals.base64(keys.public.encoded), payload, signature))
    }

    @Test
    fun `the requests are the spec's`() {
        assertEquals("""{"public_key":"MFkw","algorithm":"ES256","pin":"482916"}""", Approvals.enrollBody("MFkw", "482916"))
        assertEquals("""{"device_id":4,"signature":"MEQ"}""", Approvals.confirmBody(4, "MEQ"))
        assertTrue(Approvals.FINGERPRINT)
        assertTrue(Approvals.WINDOW)
    }
}
