package io.github.helloupendra.ira.store

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * The device token, kept with a key that lives in the Android Keystore.
 *
 * An AES-256 key is created inside the Keystore (it never leaves it), the token is
 * encrypted with AES-GCM, and only the ciphertext is written to the app's private
 * preferences. The token is never logged and never written anywhere else.
 */
class SecretStore(context: Context) {
    private val prefs = context.getSharedPreferences("ira_secrets", Context.MODE_PRIVATE)

    fun saveToken(token: String) {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val sealed = cipher.doFinal(token.toByteArray(Charsets.UTF_8))
        prefs.edit()
            .putString(IV, Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .putString(TOKEN, Base64.encodeToString(sealed, Base64.NO_WRAP))
            .apply()
    }

    fun token(): String? {
        val iv = prefs.getString(IV, null) ?: return null
        val sealed = prefs.getString(TOKEN, null) ?: return null
        return try {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)))
            String(cipher.doFinal(Base64.decode(sealed, Base64.NO_WRAP)), Charsets.UTF_8)
        } catch (_: Exception) {
            null // the key was lost (a restore to a new phone): pair again
        }
    }

    fun clear() {
        prefs.edit().clear().apply()
        try {
            KeyStore.getInstance(KEYSTORE).apply { load(null) }.deleteEntry(ALIAS)
        } catch (_: Exception) {
        }
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        (store.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }

    private companion object {
        const val KEYSTORE = "AndroidKeyStore"
        const val ALIAS = "ira_device_token"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV = "token_iv"
        const val TOKEN = "token"
    }
}
