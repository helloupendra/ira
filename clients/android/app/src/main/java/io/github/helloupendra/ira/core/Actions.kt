package io.github.helloupendra.ira.core

import java.io.IOException
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/**
 * Confirming a Tier 3 action with the PIN, typed on the phone (never spoken):
 * `POST /v1/actions/{id}/confirm` with the device token, as `docs/devices.md` allows.
 */
object Actions {
    data class Outcome(
        /** executed, failed, wrong_pin, locked, expired, ... as the server says. */
        val status: String,
        /** What to show the person, in plain words. */
        val message: String,
        val done: Boolean,
    )

    fun confirmBody(pin: String): String = buildJsonObject { put("pin", JsonPrimitive(pin)) }.toString()

    fun confirm(server: String, token: String, actionId: String, pin: String, post: HttpPost): Outcome {
        if (!Regex("^[A-Za-z0-9_-]{1,80}$").matches(actionId)) return Outcome("bad", "That action cannot be confirmed here.", false)
        val reply =
            try {
                post.post(
                    "${server.trimEnd('/')}/v1/actions/$actionId/confirm",
                    confirmBody(pin),
                    mapOf("Content-Type" to "application/json", "Authorization" to "Bearer $token"),
                )
            } catch (_: IOException) {
                return Outcome("offline", "Could not reach your Ira. Check that the phone is online, then try again.", false)
            }
        return parse(reply)
    }

    fun parse(reply: HttpReply): Outcome {
        val body = parseObject(reply.body)
        val status = body?.string("status") ?: ""
        val server = (body?.string("message") ?: body?.string("detail"))?.takeIf { it.isNotBlank() }
        val left = body?.int("attempts_left")
        val lockedSeconds = body?.int("locked_seconds")
        return when {
            reply.status == 401 || (reply.status == 403 && status.isEmpty()) ->
                Outcome("refused", "Your Ira did not accept this phone. Pair it again in Settings.", false)
            status == "executed" -> Outcome(status, server ?: "Done.", true)
            status == "wrong_pin" ->
                Outcome(status, "That PIN is not right." + (left?.let { " $it tries left before actions lock for 15 minutes." } ?: ""), false)
            status == "locked" ->
                Outcome(status, "Actions are locked after wrong PINs." + (lockedSeconds?.let { " Try again in ${(it + 59) / 60} min." } ?: ""), false)
            status == "no_pin" -> Outcome(status, "Set an action PIN on your Ira first (Your account), then try again.", false)
            status == "expired" -> Outcome(status, "That request expired. Ask Ira again.", false)
            status == "failed" -> Outcome(status, server ?: "It did not work.", true)
            status == "already_done" -> Outcome(status, "That was already done.", true)
            status == "cancelled" -> Outcome(status, "That was cancelled.", true)
            status == "not_allowed" || status == "needs_pin" ->
                Outcome(status, server ?: "Your role on this Ira cannot confirm that. Ask the Ira's owner.", false)
            status == "not_found" || reply.status == 404 -> Outcome("gone", "That request is no longer waiting. Ask Ira again.", false)
            else -> Outcome(status.ifEmpty { "error" }, server ?: "Your Ira answered HTTP ${reply.status}.", false)
        }
    }
}
