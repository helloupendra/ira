package io.github.helloupendra.ira.core

import java.security.KeyFactory
import java.security.MessageDigest
import java.security.Signature
import java.security.spec.X509EncodedKeySpec
import java.util.Base64
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/**
 * Fewer PINs for one task (`docs/security.md`, Approvals; the owner: "PIN ek baar set karun,
 * fir baar baar na maange").
 *
 * - **The approval window** (on): a right PIN on a covered action opens a window for this
 *   person on this device; for its minutes, screen and app control here runs without asking.
 *   The phone shows it, counts it down, and can stop it; only a PIN opens or lengthens one.
 * - **A device key** (designed on the server, not built yet, so behind [FINGERPRINT]): an EC
 *   P-256 key in the Android Keystore, unlocked by a fingerprint, approves instead of the PIN.
 */
object Approvals {
    /** The approval window: on, the server has it. */
    const val WINDOW = true

    /** Fingerprint approval: off until the server has `/v1/me/approval-keys`. */
    const val FINGERPRINT = false

    const val PATH = "/v1/me/approvals"
    const val KEYS_PATH = "/v1/me/approval-keys"
    const val KEY_ALGORITHM = "EC"
    const val SIGNATURE_ALGORITHM = "SHA256withECDSA"

    // What a window covers.

    private val COVERED = setOf("screen_read", "screen_act", "app_open", "url_open", "media_play", "media_control", "settings_toggle")
    private val NEVER = listOf("send", "reply", "call", "place", "pay", "payment", "buy", "transfer", "delete", "remove", "push", "grant", "pair")

    /** Whether an open window covers this tool: screen and app control, never the never-list. */
    fun covered(tool: String): Boolean = tool in COVERED && NEVER.none { tool.contains(it) }

    // The window.

    data class Window(val id: String, val deviceId: Int?, val device: String, val openedAt: Double, val expiresAt: Double, val steps: Int) {
        fun secondsLeft(now: Double): Long = maxOf(0L, kotlin.math.ceil(expiresAt - now).toLong())
    }

    data class Status(val minutes: Int, val windows: List<Window>) {
        /** This device's open window, the one lasting longest. */
        fun forDevice(deviceId: Int, now: Double): Window? =
            windows.filter { it.deviceId == deviceId && it.expiresAt > now }.maxByOrNull { it.expiresAt }

        companion object {
            /** `GET /v1/me/approvals`; null when the answer is not one. */
            fun parse(body: String): Status? {
                val m = parseObject(body) ?: return null
                val minutes = m.int("minutes") ?: return null
                val windows =
                    m.array("windows").orEmpty().mapNotNull { item ->
                        val w = item as? JsonObject ?: return@mapNotNull null
                        Window(
                            id = w.string("id") ?: w.long("id")?.toString() ?: return@mapNotNull null,
                            deviceId = w.int("device_id"),
                            device = w.string("device").orEmpty(),
                            openedAt = w.double("opened_at") ?: 0.0,
                            expiresAt = w.double("expires_at") ?: return@mapNotNull null,
                            steps = w.int("steps") ?: 0,
                        )
                    }
                return Status(minutes, windows)
            }
        }
    }

    /** The banner while this phone's window is open; null once it has closed. */
    fun banner(secondsLeft: Long): String? =
        when {
            secondsLeft <= 0 -> null
            secondsLeft < 60 -> "Ira can use this phone for less than a minute more"
            else -> {
                val minutes = (secondsLeft + 59) / 60
                "Ira can use this phone for $minutes more minute" + if (minutes == 1L) "" else "s"
            }
        }

    /** A window id as a path segment, or null when it is not a safe one. */
    fun windowPath(id: String): String? = if (Regex("^[A-Za-z0-9_-]{1,80}$").matches(id)) "$PATH/$id" else null

    // The device key (behind FINGERPRINT).

    fun sha256Hex(text: String): String =
        MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }

    /**
     * The exact bytes a fingerprint approval signs, UTF-8: the version, the action, the hash of
     * the summary the person was shown, and the action's expiry in whole seconds.
     */
    fun payload(actionId: String, summary: String, expiresAt: Long): ByteArray {
        require(Regex("^[A-Za-z0-9_-]{1,80}$").matches(actionId)) { "bad action id" }
        return "ira-approve:1\n$actionId\n${sha256Hex(summary)}\n$expiresAt".toByteArray(Charsets.UTF_8)
    }

    fun base64(bytes: ByteArray): String = Base64.getEncoder().encodeToString(bytes)

    /** A signature as the server takes it: base64url, without padding. */
    fun base64url(bytes: ByteArray): String = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)

    /** `POST /v1/me/approval-keys`: the public key (SubjectPublicKeyInfo, DER, base64) and the PIN. */
    fun enrollBody(publicKeyBase64: String, pin: String): String =
        buildJsonObject {
            put("public_key", JsonPrimitive(publicKeyBase64))
            put("algorithm", JsonPrimitive("ES256"))
            put("pin", JsonPrimitive(pin))
        }.toString()

    /** `POST /v1/actions/{id}/confirm` with a signature in place of the PIN. */
    fun confirmBody(deviceId: Int, signatureBase64url: String): String =
        buildJsonObject {
            put("device_id", JsonPrimitive(deviceId))
            put("signature", JsonPrimitive(signatureBase64url))
        }.toString()

    /** What the server does: check a base64url DER signature over [payload] with the enrolled key. */
    fun verify(publicKeyBase64: String, payload: ByteArray, signatureBase64url: String): Boolean =
        try {
            val key = KeyFactory.getInstance(KEY_ALGORITHM).generatePublic(X509EncodedKeySpec(Base64.getDecoder().decode(publicKeyBase64)))
            Signature.getInstance(SIGNATURE_ALGORITHM).run {
                initVerify(key)
                update(payload)
                verify(Base64.getUrlDecoder().decode(signatureBase64url))
            }
        } catch (_: Exception) {
            false
        }
}
