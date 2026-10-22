package io.github.helloupendra.ira.core

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/**
 * What the app needs of `GET /v1/info`: whether a live call works on this server, and
 * whether the server has a voice of its own.
 */
data class ServerInfo(
    val name: String,
    /** `/v1/voice/live` works: streaming speech-to-text, a voice, and the role may talk. */
    val live: Boolean,
    /** The server's text-to-speech (`polly`, `fake`...), or null: the phone speaks instead. */
    val tts: String?,
    /** The language to recognise on the phone: hi-IN for Hindi or Hinglish, else en-IN. */
    val micLanguage: String,
) {
    companion object {
        fun parse(body: String): ServerInfo? {
            val m = parseObject(body) ?: return null
            val name = m.string("name") ?: return null
            return ServerInfo(
                name = name,
                live = m.bool("live") == true,
                tts = m.string("tts")?.takeIf { it.isNotBlank() },
                micLanguage = m.string("mic_language")?.takeIf { it == "hi-IN" || it == "en-IN" } ?: "en-IN",
            )
        }
    }
}

/**
 * `POST /v1/ask/stream` (`docs/api.md`, Streaming): one JSON event per `data:` line of
 * server-sent events, told apart by `type`. The way the app talks to Ira when no live call is
 * on: typed text, and speech the phone itself recognised.
 */
object AskStream {
    const val PATH = "/v1/ask/stream"

    fun body(text: String, conversationId: String?): String =
        buildJsonObject {
            put("text", JsonPrimitive(text))
            if (!conversationId.isNullOrBlank()) put("conversation_id", JsonPrimitive(conversationId))
        }.toString()

    sealed interface Event {
        data class Start(val conversationId: String) : Event

        data class Tool(val name: String) : Event

        data class Action(val card: ActionCard) : Event

        data class Delta(val text: String) : Event

        data class Error(val message: String) : Event

        data class Done(val text: String, val conversationId: String, val messageId: Long?) : Event
    }

    /** One line of the stream: an event for a `data:` line, null for anything else. */
    fun parseLine(line: String): Event? {
        if (!line.startsWith("data:")) return null
        val m = parseObject(line.removePrefix("data:").trim()) ?: return null
        return when (m.string("type")) {
            "start" -> Event.Start(m.string("conversation_id").orEmpty())
            "tool" -> Event.Tool(m.string("name").orEmpty())
            "action" -> Event.Action(ActionCard.from(m.obj("action") ?: JsonObject(emptyMap())))
            "delta" -> Event.Delta(m.string("text").orEmpty())
            "error" -> Event.Error(m.string("message") ?: "no model could answer")
            "done" -> Event.Done(m.string("text").orEmpty(), m.string("conversation_id").orEmpty(), m.long("message_id"))
            else -> null
        }
    }

    /** What to tell the person when the request itself failed, by HTTP status. */
    fun failure(status: Int): String =
        when (status) {
            401, 403 -> "Your Ira did not accept this phone. Pair it again in Settings."
            413, 422 -> "That message is too long for Ira. Shorten it and send it again."
            429 -> "Ira is busy just now. Send it again in a minute."
            in 500..599 -> "Your Ira had a problem answering. Send it again in a moment."
            else -> "Your Ira answered HTTP $status. Send it again in a moment."
        }

    const val OFFLINE = "Could not reach your Ira. Check that the phone is online, then send it again."
}
