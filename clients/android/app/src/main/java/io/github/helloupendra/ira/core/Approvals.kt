package io.github.helloupendra.ira.core

import java.security.KeyFactory
import java.security.Signature
import java.security.spec.X509EncodedKeySpec
import java.util.Base64

/**
 * Approving once instead of at every step (the owner: "PIN ek baar set karun, fir baar baar
 * na maange"). Three parts, all on the person's own Ira:
 *
 * - **A device key**: enrolled once with the PIN. An EC P-256 key made inside the Android
 *   Keystore, usable only after a fingerprint (or the screen lock), signs each approval; the
 *   server checks it with the public key it was given. The PIN stays the fallback.
 * - **A trust window**: for a few minutes after one approval, screen, app and link actions run
 *   without asking again. Never sending, calling, paying or deleting.
 * - **Trusted apps**, such as YouTube: adding one needs the PIN.
 *
 * The server's API for these is not published yet ([Server] is the seam); until it is, the
 * screens stay behind [ENABLED] and the server stand-in says so plainly.
 */
object Approvals {
    /** Off until the server's approvals API exists; then wire [Server] and switch it on. */
    const val ENABLED = false

    /** The trust windows offered, in minutes. */
    val WINDOWS = listOf(5, 15, 30, 60)

    const val KEY_ALGORITHM = "EC"
    const val SIGNATURE_ALGORITHM = "SHA256withECDSA"

    /**
     * The exact bytes a fingerprint approval signs: a fixed prefix, the device, the action and
     * its expiry, one per line, so a signature for one action can never approve another.
     */
    fun payload(deviceId: Int, actionId: String, expiresAt: Long): ByteArray {
        require(Regex("^[A-Za-z0-9_-]{1,80}$").matches(actionId)) { "bad action id" }
        return "ira-approve-v1\n$deviceId\n$actionId\n$expiresAt".toByteArray(Charsets.UTF_8)
    }

    fun base64(bytes: ByteArray): String = Base64.getEncoder().encodeToString(bytes)

    /** What the server will do: check [signature] over [payload] with the enrolled public key. */
    fun verify(publicKeyBase64: String, payload: ByteArray, signatureBase64: String): Boolean =
        try {
            val key = KeyFactory.getInstance(KEY_ALGORITHM).generatePublic(X509EncodedKeySpec(Base64.getDecoder().decode(publicKeyBase64)))
            Signature.getInstance(SIGNATURE_ALGORITHM).run {
                initVerify(key)
                update(payload)
                verify(Base64.getDecoder().decode(signatureBase64))
            }
        } catch (_: Exception) {
            false
        }

    /** The banner while a trust window is open; null once it has closed. */
    fun banner(secondsLeft: Long): String? =
        when {
            secondsLeft <= 0 -> null
            secondsLeft < 60 -> "Ira can tap and type for less than a minute more"
            else -> {
                val minutes = (secondsLeft + 59) / 60
                "Ira can tap and type for $minutes more minute" + if (minutes == 1L) "" else "s"
            }
        }

    /** A trusted app is named by its package, as Android knows it. */
    fun checkPackage(pkg: String): String {
        val clean = pkg.trim()
        if (!Regex("^[a-zA-Z][a-zA-Z0-9_]*(\\.[a-zA-Z][a-zA-Z0-9_]*)+$").matches(clean) || clean.length > 120) {
            throw IllegalArgumentException("'$pkg' is not an app's package name")
        }
        return clean
    }

    /** Actions a trust window may cover; sending, calling, paying and deleting never. */
    fun trustable(tool: String): Boolean = tool in setOf("screen_read", "screen_act", "app_open", "url_open", "media_play")

    /** The person's Ira, for approvals. Each call answers with null, or what went wrong in plain words. */
    interface Server {
        fun enroll(pin: String, publicKeyBase64: String): String?

        fun approve(actionId: String, payloadBase64: String, signatureBase64: String): String?

        /** Open a trust window; null, or what went wrong. */
        fun trust(minutes: Int): String?

        fun stopTrust(): String?

        fun addTrustedApp(pkg: String, pin: String): String?

        fun removeTrustedApp(pkg: String): String?
    }

    /** Until the server publishes its approvals API. */
    object NotYet : Server {
        const val MESSAGE = "Your Ira does not offer approvals yet. Confirm with your PIN for now."

        override fun enroll(pin: String, publicKeyBase64: String) = MESSAGE

        override fun approve(actionId: String, payloadBase64: String, signatureBase64: String) = MESSAGE

        override fun trust(minutes: Int) = MESSAGE

        override fun stopTrust() = MESSAGE

        override fun addTrustedApp(pkg: String, pin: String) = MESSAGE

        override fun removeTrustedApp(pkg: String) = MESSAGE
    }
}
