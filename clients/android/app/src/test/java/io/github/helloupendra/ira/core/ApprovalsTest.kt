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
    /** The same kind of key the Keystore makes: EC P-256, signatures SHA256withECDSA. */
    private val keys = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()

    private fun sign(payload: ByteArray): String =
        Approvals.base64(Signature.getInstance(Approvals.SIGNATURE_ALGORITHM).run {
            initSign(keys.private)
            update(payload)
            sign()
        })

    @Test
    fun `an approval signs one device, one action and its expiry`() {
        assertEquals("ira-approve-v1\n3\nact_1f2e\n1792700000", String(Approvals.payload(3, "act_1f2e", 1_792_700_000), Charsets.UTF_8))
        assertThrows(IllegalArgumentException::class.java) { Approvals.payload(3, "act\n4", 1) }
    }

    @Test
    fun `the server can check a signature with the enrolled public key, and only for that action`() {
        val publicKey = Approvals.base64(keys.public.encoded) // X.509, as Keystore's public key encodes
        val payload = Approvals.payload(3, "act_1", 1_792_700_000)
        val signature = sign(payload)
        assertTrue(Approvals.verify(publicKey, payload, signature))
        assertFalse(Approvals.verify(publicKey, Approvals.payload(3, "act_2", 1_792_700_000), signature))
        assertFalse(Approvals.verify(publicKey, Approvals.payload(4, "act_1", 1_792_700_000), signature))
        assertFalse(Approvals.verify(publicKey, Approvals.payload(3, "act_1", 1_792_700_060), signature))
        assertFalse(Approvals.verify("not a key", payload, signature))
    }

    @Test
    fun `the trust window offers four lengths, and its banner counts down`() {
        assertEquals(listOf(5, 15, 30, 60), Approvals.WINDOWS)
        assertEquals("Ira can tap and type for 12 more minutes", Approvals.banner(11 * 60 + 1))
        assertEquals("Ira can tap and type for 1 more minute", Approvals.banner(60))
        assertEquals("Ira can tap and type for less than a minute more", Approvals.banner(30))
        assertNull(Approvals.banner(0))
    }

    @Test
    fun `a trust window never covers sending, calling, paying or deleting`() {
        assertTrue(Approvals.trustable("screen_act"))
        assertTrue(Approvals.trustable("url_open"))
        for (never in listOf("sms_send", "call_place", "notification_reply", "calendar_add")) assertFalse(never, Approvals.trustable(never))
    }

    @Test
    fun `trusted apps are packages`() {
        assertEquals("com.google.android.youtube", Approvals.checkPackage(" com.google.android.youtube "))
        for (bad in listOf("YouTube", "com..x", "../etc", "")) assertThrows(bad, IllegalArgumentException::class.java) { Approvals.checkPackage(bad) }
    }

    @Test
    fun `until the server offers approvals, every call says so and nothing changes`() {
        assertFalse(Approvals.ENABLED)
        assertEquals(Approvals.NotYet.MESSAGE, Approvals.NotYet.enroll("482916", "key"))
        assertEquals(Approvals.NotYet.MESSAGE, Approvals.NotYet.trust(15))
    }
}
