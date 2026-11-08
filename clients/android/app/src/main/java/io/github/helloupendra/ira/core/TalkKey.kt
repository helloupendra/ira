package io.github.helloupendra.ira.core

import java.security.MessageDigest
import java.util.UUID

/**
 * A key that lives only in this app's process. Ira's own assistant session sends it with the
 * intent that starts the microphone, so another app sending the same action starts nothing.
 */
object TalkKey {
    const val EXTRA = "io.github.helloupendra.ira.extra.TALK_KEY"

    val value: String = UUID.randomUUID().toString()

    fun matches(key: String?): Boolean =
        key != null && MessageDigest.isEqual(key.toByteArray(), value.toByteArray())
}
