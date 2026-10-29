package io.github.helloupendra.ira.core

import java.io.IOException
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/**
 * Answering an action card with the device token, as `docs/devices.md` allows: a Tier 3
 * action with the PIN, typed on the phone (never spoken), `POST /v1/actions/{id}/confirm`;
 * a Tier 2 one with Yes or No, `POST /v1/actions/{id}/approve` or `/cancel`.
 */
object Actions {
    data class Outcome(
        /** executed, failed, wrong_pin, locked, expired, ... as the server says. */
        val status: String,
        /** What to show the person, in plain words. */
        val message: String,
        /** The action is over (done, failed, gone): its card should go. */
        val done: Boolean,
        /** A short form of what the action returned, for the result card. */
        val detail: String? = null,
        /** Ira's answer after the action ran (the model carries on), to show as its next message. */
        val reply: String? = null,
        val replyMessageId: Long? = null,
        /** The answer was spoken in the open live call instead, as its own turn: no bubble here. */
        val continuedInCall: Boolean = false,
    )

    /** What an action returned, short: its `summary`, its text, or its JSON cut to 200 characters. */
    fun detail(result: kotlinx.serialization.json.JsonElement?): String? {
        val text =
            when (result) {
                null, is kotlinx.serialization.json.JsonNull -> return null
                is JsonObject -> result.string("summary") ?: result.toString()
                is kotlinx.serialization.json.JsonPrimitive -> result.content
                else -> result.toString()
            }.trim()
        if (text.isEmpty()) return null
        return if (text.length <= 200) text else text.take(199) + "…"
    }

    fun confirmBody(pin: String): String = buildJsonObject { put("pin", JsonPrimitive(pin)) }.toString()

    fun confirm(server: String, token: String, actionId: String, pin: String, post: HttpPost): Outcome =
        send(server, token, actionId, "confirm", confirmBody(pin), post)

    /**
     * Yes or no to this card's own action, by its id: never the word "yes" in the chat, which
     * could answer a newer action, or be lost while Ira is still talking.
     */
    fun answer(server: String, token: String, actionId: String, yes: Boolean, post: HttpPost): Outcome =
        send(server, token, actionId, if (yes) "approve" else "cancel", "{}", post)

    private fun send(server: String, token: String, actionId: String, verb: String, body: String, post: HttpPost): Outcome {
        if (!Regex("^[A-Za-z0-9_-]{1,80}$").matches(actionId)) return Outcome("bad", "That action cannot be confirmed here.", false)
        val reply =
            try {
                post.post(
                    "${server.trimEnd('/')}/v1/actions/$actionId/$verb",
                    body,
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
        val after = { outcome: Outcome ->
            outcome.copy(
                reply = body?.string("reply")?.takeIf { it.isNotBlank() },
                replyMessageId = body?.long("reply_message_id"),
                continuedInCall = body?.bool("continued_in_call") == true,
            )
        }
        return when {
            reply.status == 401 || (reply.status == 403 && status.isEmpty()) ->
                Outcome("refused", "Your Ira did not accept this phone. Pair it again in Settings.", false)
            status == "executed" -> after(Outcome(status, server ?: "Done.", true, detail(body?.get("result"))))
            status == "wrong_pin" ->
                Outcome(status, "That PIN is not right." + (left?.let { " $it tries left before actions lock for 15 minutes." } ?: ""), false)
            status == "locked" ->
                Outcome(status, "Actions are locked after wrong PINs." + (lockedSeconds?.let { " Try again in ${(it + 59) / 60} min." } ?: ""), false)
            status == "no_pin" -> Outcome(status, "Set an action PIN on your Ira first (Your account), then try again.", false)
            status == "expired" -> Outcome(status, "That request expired. Ask Ira again.", true)
            status == "failed" -> after(Outcome(status, server ?: "It did not work.", true, detail(body?.get("result"))))
            status == "already_done" -> Outcome(status, "That was already done.", true)
            status == "cancelled" -> Outcome(status, "That was cancelled.", true)
            status == "not_allowed" || status == "needs_pin" ->
                Outcome(status, server ?: "Your role on this Ira cannot confirm that. Ask the Ira's owner.", false)
            status == "not_found" || reply.status == 404 -> Outcome("gone", "That request is no longer waiting. Ask Ira again.", true)
            else -> Outcome(status.ifEmpty { "error" }, server ?: "Your Ira answered HTTP ${reply.status}.", false)
        }
    }
}
