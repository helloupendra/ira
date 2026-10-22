package io.github.helloupendra.ira.core

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/**
 * Real-time voice, protocol 1 (`docs/realtime.md`): `GET /v1/voice/live`.
 *
 * Up: JSON text frames, and binary frames of PCM16 LE mono 16 kHz audio, only while the
 * person speaks. Down: JSON text frames, and after each `audio` message one binary frame
 * with that sentence as MP3.
 */
object LiveProtocol {
    const val VERSION = 1
    const val PATH = "/v1/voice/live"
    const val SAMPLE_RATE = 16_000

    /** 20 to 100 ms of 16-bit mono audio at 16 kHz. */
    const val MIN_AUDIO_BYTES = 640
    const val MAX_AUDIO_BYTES = 3_200

    fun start(client: String, conversationId: String?): String =
        buildJsonObject {
            put("type", JsonPrimitive("start"))
            put("protocol", JsonPrimitive(VERSION))
            put("client", JsonPrimitive(client))
            if (!conversationId.isNullOrBlank()) put("conversation_id", JsonPrimitive(conversationId))
        }.toString()

    fun speechStart(at: Double): String = timed("speech_start", at)

    fun speechEnd(at: Double): String = timed("speech_end", at)

    fun text(text: String): String =
        buildJsonObject {
            put("type", JsonPrimitive("text"))
            put("text", JsonPrimitive(text))
        }.toString()

    fun interrupt(): String = plain("interrupt")

    fun played(turn: Int, at: Double): String =
        buildJsonObject {
            put("type", JsonPrimitive("played"))
            put("turn", JsonPrimitive(turn))
            put("at", JsonPrimitive(round1(at)))
        }.toString()

    fun pong(): String = plain("pong")

    fun bye(): String = plain("bye")

    private fun plain(type: String) = buildJsonObject { put("type", JsonPrimitive(type)) }.toString()

    private fun timed(type: String, at: Double) =
        buildJsonObject {
            put("type", JsonPrimitive(type))
            put("at", JsonPrimitive(round1(at)))
        }.toString()

    private fun round1(value: Double) = Math.round(value * 10.0) / 10.0

    /**
     * Split audio into frames the server accepts: 640 to 3,200 bytes, whole samples.
     * A tail shorter than 640 bytes still goes (the last frame of an utterance may be short).
     */
    fun chunks(pcm: ByteArray, size: Int = MAX_AUDIO_BYTES): List<ByteArray> {
        require(size in MIN_AUDIO_BYTES..MAX_AUDIO_BYTES && size % 2 == 0)
        if (pcm.size <= size) return listOf(pcm)
        val out = ArrayList<ByteArray>()
        var from = 0
        while (from < pcm.size) {
            val to = minOf(pcm.size, from + size)
            out.add(pcm.copyOfRange(from, to))
            from = to
        }
        return out
    }

    /** Parse one text frame from the server; unknown or broken frames come back as [Live.Unknown]. */
    fun parse(text: String): Live {
        val m = parseObject(text) ?: return Live.Unknown("not a JSON object")
        return when (val type = m.string("type")) {
            "ready" ->
                Live.Ready(
                    protocol = m.int("protocol") ?: 0,
                    conversationId = m.string("conversation_id").orEmpty(),
                    assistant = m.string("assistant") ?: "Ira",
                    languages = m.strings("languages"),
                    tts = m.string("tts"),
                )
            "partial" -> Live.Partial(m.string("text").orEmpty(), m.string("language"))
            "heard" -> Live.Heard(m.int("turn") ?: 0, m.string("text").orEmpty(), m.string("language"))
            "delta" -> Live.Delta(m.int("turn") ?: 0, m.string("text").orEmpty())
            "audio" ->
                Live.AudioHeader(
                    turn = m.int("turn") ?: 0,
                    seq = m.int("seq") ?: 0,
                    text = m.string("text").orEmpty(),
                    format = m.string("format") ?: "mp3",
                    bytes = m.int("bytes") ?: -1,
                )
            "action" -> Live.Action(m.int("turn") ?: 0, ActionCard.from(m.obj("action") ?: JsonObject(emptyMap())))
            "done" ->
                Live.Done(
                    turn = m.int("turn") ?: 0,
                    text = m.string("text").orEmpty(),
                    messageId = m.long("message_id"),
                )
            "interrupted" -> Live.Interrupted(m.int("turn") ?: 0)
            "ping" -> Live.Ping
            "error" -> Live.Error(m.string("message") ?: "something went wrong", m.bool("fatal") == true)
            else -> Live.Unknown("unknown type '${type ?: ""}'")
        }
    }
}

/** What the server says on the live connection. */
sealed interface Live {
    data class Ready(
        val protocol: Int,
        val conversationId: String,
        val assistant: String,
        val languages: List<String>,
        val tts: String?,
    ) : Live

    data class Partial(val text: String, val language: String?) : Live

    data class Heard(val turn: Int, val text: String, val language: String?) : Live

    data class Delta(val turn: Int, val text: String) : Live

    /** The next binary frame is this sentence's audio. */
    data class AudioHeader(val turn: Int, val seq: Int, val text: String, val format: String, val bytes: Int) : Live

    data class Action(val turn: Int, val card: ActionCard) : Live

    data class Done(val turn: Int, val text: String, val messageId: Long?) : Live

    data class Interrupted(val turn: Int) : Live

    data object Ping : Live

    data class Error(val message: String, val fatal: Boolean) : Live

    data class Unknown(val why: String) : Live
}

/** A proposed action, as `/v1/ask` shows it: Tier 2 needs a yes, Tier 3 the PIN in the Ira app. */
data class ActionCard(
    val id: String,
    val tool: String,
    val summary: String,
    val tier: Int,
    val canApprove: Boolean,
    val expiresIn: Int?,
) {
    val needsPin: Boolean
        get() = tier >= 3

    companion object {
        fun from(m: JsonObject): ActionCard =
            ActionCard(
                id = m.string("id") ?: m.long("id")?.toString().orEmpty(),
                tool = m.string("tool").orEmpty(),
                summary = m.string("summary") ?: m.string("tool").orEmpty(),
                tier = m.int("tier") ?: 3,
                canApprove = m.bool("can_approve") == true,
                expiresIn = m.int("expires_in"),
            )
    }
}

/** One sentence of Ira's voice, ready to play. */
class SentenceAudio(val turn: Int, val seq: Int, val text: String, val mp3: ByteArray)

/**
 * Pairs each `audio` header with the binary frame that follows it, keeps each turn's
 * sentences in `seq` order, and drops the audio of turns that were interrupted.
 *
 * The server sends a header and its bytes together, but a client must still cope with a
 * binary frame that has no header, a header whose frame never came, a frame whose size is
 * not the one announced, and audio that was in flight when the person barged in.
 */
class AudioAssembler(private val maxHeld: Int = 32) {
    private var pending: Live.AudioHeader? = null
    private val nextSeq = HashMap<Int, Int>()
    private val held = HashMap<Int, MutableMap<Int, SentenceAudio>>()

    /** Audio of this turn and every earlier one is dropped. */
    var droppedThrough: Int = 0
        private set

    /** Problems seen (counted, never logged with content). */
    var discarded: Int = 0
        private set

    /** A text frame arrived. Returns nothing: only binary frames release audio. */
    fun onMessage(message: Live) {
        if (pending != null) {
            // A header must be followed by its binary frame; anything else orphans it.
            pending = null
            discarded++
        }
        if (message is Live.AudioHeader) pending = message
        if (message is Live.Interrupted) drop(message.turn)
    }

    /** A binary frame arrived: the sentences now ready to play, in order. */
    fun onBinary(bytes: ByteArray): List<SentenceAudio> {
        val header = pending
        pending = null
        if (header == null) {
            discarded++
            return emptyList()
        }
        if ((header.bytes >= 0 && header.bytes != bytes.size) || header.turn <= droppedThrough) {
            discarded++
            if (header.turn > droppedThrough) skip(header)
            return emptyList()
        }
        val turn = held.getOrPut(header.turn) { HashMap() }
        if (turn.size >= maxHeld) {
            discarded++
            return emptyList()
        }
        turn[header.seq] = SentenceAudio(header.turn, header.seq, header.text, bytes)
        return release(header.turn)
    }

    /** Drop everything of [turn] and earlier: a barge-in, or `interrupted` from the server. */
    fun drop(turn: Int) {
        if (turn > droppedThrough) droppedThrough = turn
        held.keys.filter { it <= droppedThrough }.forEach { held.remove(it) }
        nextSeq.keys.filter { it <= droppedThrough }.forEach { nextSeq.remove(it) }
        pending?.let { if (it.turn <= droppedThrough) pending = null }
    }

    private fun skip(header: Live.AudioHeader) {
        // A broken sentence must not stall the ones after it.
        val expected = nextSeq[header.turn] ?: 0
        if (header.seq == expected) {
            nextSeq[header.turn] = expected + 1
        }
    }

    private fun release(turn: Int): List<SentenceAudio> {
        val waiting = held[turn] ?: return emptyList()
        var seq = nextSeq[turn] ?: 0
        val out = ArrayList<SentenceAudio>()
        while (true) {
            val next = waiting.remove(seq) ?: break
            out.add(next)
            seq++
        }
        nextSeq[turn] = seq
        // A gap that never fills (a lost sentence) is skipped once later ones pile up.
        if (out.isEmpty() && waiting.size >= 3) {
            val first = waiting.keys.min()
            nextSeq[turn] = first
            discarded++
            return release(turn)
        }
        return out
    }
}
