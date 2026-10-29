package io.github.helloupendra.ira.approvals

import android.app.Activity
import android.content.Context
import android.hardware.biometrics.BiometricManager
import android.hardware.biometrics.BiometricManager.Authenticators
import android.hardware.biometrics.BiometricPrompt
import android.os.Build
import android.os.CancellationSignal
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import io.github.helloupendra.ira.core.Approvals
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec

/**
 * This phone's approval key: EC P-256, made inside the Android Keystore, never leaving it,
 * and usable only right after a fingerprint. Never the screen lock: someone who knows the
 * unlock pattern must still type the action PIN, which the server counts. A new fingerprint
 * added to the phone invalidates the key, and the phone is enrolled again.
 */
object DeviceKey {
    private const val KEYSTORE = "AndroidKeyStore"
    private const val ALIAS = "ira_approval"

    fun exists(): Boolean = keyStore().containsAlias(ALIAS)

    /** The key is there and still works: a fingerprint added since makes it unusable. */
    fun usable(): Boolean = exists() && signature() != null

    /** Why this phone cannot use a fingerprint for approvals, or null when it can. */
    fun unsupported(context: Context): String? =
        when (context.getSystemService(BiometricManager::class.java)?.canAuthenticate(Authenticators.BIOMETRIC_STRONG)) {
            BiometricManager.BIOMETRIC_SUCCESS -> null
            BiometricManager.BIOMETRIC_ERROR_NONE_ENROLLED -> "Add a fingerprint to this phone first (in its Security settings)."
            BiometricManager.BIOMETRIC_ERROR_NO_HARDWARE, BiometricManager.BIOMETRIC_ERROR_HW_UNAVAILABLE ->
                "This phone has no fingerprint reader Ira can use. Approve with your PIN."
            else -> "This phone cannot use a fingerprint for approvals now. Approve with your PIN."
        }

    /** Make the key (replacing any old one); returns its public key, X.509, in base64. */
    fun create(): String {
        delete()
        val spec =
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
                .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_SHA256)
                .setUserAuthenticationRequired(true)
                .setInvalidatedByBiometricEnrollment(true)
                .apply {
                    // Every use needs a fresh fingerprint (before Android 11, that is the default).
                    if (Build.VERSION.SDK_INT >= 30) setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG)
                }
                .build()
        val generator = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, KEYSTORE)
        generator.initialize(spec)
        return Approvals.base64(generator.generateKeyPair().public.encoded)
    }

    fun delete() {
        try {
            keyStore().deleteEntry(ALIAS)
        } catch (_: Exception) {
        }
    }

    /** A signature ready for the fingerprint prompt, or null when the key is gone or invalidated. */
    fun signature(): Signature? =
        try {
            val key = keyStore().getKey(ALIAS, null) as? PrivateKey ?: return null
            Signature.getInstance(Approvals.SIGNATURE_ALGORITHM).apply { initSign(key) }
        } catch (_: Exception) {
            null
        }

    private fun keyStore(): KeyStore = KeyStore.getInstance(KEYSTORE).apply { load(null) }
}

/** Approve one action with a fingerprint: the prompt unlocks the key, which signs [payload]. */
object Fingerprint {
    fun approve(activity: Activity, what: String, payload: ByteArray, done: (signature: String?, error: String?) -> Unit) {
        val signature = DeviceKey.signature() ?: return done(null, "This phone's approval key is gone (a new fingerprint was added?). Enroll it again in Settings, Approvals, or use the PIN.")
        val builder =
            BiometricPrompt.Builder(activity)
                .setTitle("Approve with fingerprint")
                .setSubtitle(what.take(120))
                .setNegativeButton("Use the PIN", activity.mainExecutor) { _, _ -> done(null, null) }
        if (Build.VERSION.SDK_INT >= 30) builder.setAllowedAuthenticators(Authenticators.BIOMETRIC_STRONG)
        builder.build().authenticate(
            BiometricPrompt.CryptoObject(signature),
            CancellationSignal(),
            activity.mainExecutor,
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    val unlocked = result.cryptoObject?.signature ?: return done(null, "The fingerprint did not unlock the key. Use the PIN.")
                    unlocked.update(payload)
                    done(Approvals.base64url(unlocked.sign()), null)
                }

                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    // Cancelled, or no fingerprint set up: the PIN remains.
                    done(null, if (errorCode == BiometricPrompt.BIOMETRIC_ERROR_USER_CANCELED || errorCode == BiometricPrompt.BIOMETRIC_ERROR_CANCELED) null else "$errString. Use the PIN.")
                }
            },
        )
    }
}
