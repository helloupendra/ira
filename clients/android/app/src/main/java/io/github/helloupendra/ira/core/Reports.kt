package io.github.helloupendra.ira.core

import java.io.IOException
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/**
 * Report one of Ira's answers (Google Play asks every app that shows AI-written content for
 * this): `POST /v1/me/reports` with the device token, as `docs/api.md` describes.
 */
object Reports {
    /** The server's reasons, with what the person sees. */
    val REASONS: List<Pair<String, String>> =
        listOf(
            "wrong" to "Wrong: it is not true",
            "harmful" to "Harmful: dangerous advice",
            "offensive" to "Offensive",
            "private" to "Private: it showed something it should not",
            "other" to "Something else",
        )

    const val MAX_NOTE = 500

    data class Result(val ok: Boolean, val message: String)

    fun body(messageId: Long, reason: String, note: String?): String =
        buildJsonObject {
            put("message_id", JsonPrimitive(messageId))
            put("reason", JsonPrimitive(reason))
            val clean = note?.split(Regex("\\s+"))?.filter { it.isNotEmpty() }?.joinToString(" ")?.take(MAX_NOTE)
            if (!clean.isNullOrEmpty()) put("note", JsonPrimitive(clean))
        }.toString()

    fun send(server: String, token: String, messageId: Long, reason: String, note: String?, post: HttpPost): Result {
        if (messageId <= 0) return Result(false, "This answer cannot be reported yet. Wait until Ira finishes it.")
        if (REASONS.none { it.first == reason }) return Result(false, "Pick a reason first.")
        val reply =
            try {
                post.post(
                    "${server.trimEnd('/')}/v1/me/reports",
                    body(messageId, reason, note),
                    mapOf("Content-Type" to "application/json", "Authorization" to "Bearer $token"),
                )
            } catch (_: IOException) {
                return Result(false, "Could not reach your Ira. Check that the phone is online, then try again.")
            }
        return parse(reply)
    }

    fun parse(reply: HttpReply): Result =
        when {
            reply.status in 200..299 && parseObject(reply.body)?.string("id") != null -> Result(true, "Thanks, reported. Your Ira's owner will see it.")
            reply.status == 404 -> Result(false, "That answer is no longer in your conversations, so it cannot be reported.")
            reply.status == 422 -> Result(false, "Your Ira did not accept the report. Update the app, then try again.")
            reply.status == 401 || reply.status == 403 -> Result(false, "Your Ira did not accept this phone. Pair it again in Settings.")
            reply.status in 200..299 -> Result(false, "Your Ira did not answer like an Ira server. Try again later.")
            else -> Result(false, "Your Ira answered HTTP ${reply.status}. Try again later.")
        }
}
