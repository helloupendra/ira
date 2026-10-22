package io.github.helloupendra.ira.voice

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update

/**
 * The conversation on screen, shared by a live call and the phone's own speech mode, so
 * switching between them keeps what was said. In memory only; never written anywhere.
 */
class Transcript {
    /**
     * One line. [key] tells lines apart across modes and reconnects; [messageId] is the
     * server's id of one of Ira's answers once it is complete (for Report).
     */
    data class Line(
        val key: String,
        val fromIra: Boolean,
        val text: String,
        val stopped: Boolean = false,
        val messageId: Long? = null,
    )

    private val state = MutableStateFlow<List<Line>>(emptyList())
    val lines: StateFlow<List<Line>> = state

    fun add(line: Line) {
        state.update { (it + line).takeLast(MAX_LINES) }
    }

    /** Change Ira's line [key], or start it. */
    fun ira(key: String, change: (Line) -> Line) {
        state.update { lines ->
            val index = lines.indexOfLast { it.key == key }
            val out = lines.toMutableList()
            if (index >= 0) out[index] = change(out[index]) else out += change(Line(key, true, ""))
            out.takeLast(MAX_LINES)
        }
    }

    fun stopped(key: String) {
        state.update { lines -> lines.map { if (it.key == key) it.copy(stopped = true) else it } }
    }

    private companion object {
        const val MAX_LINES = 60
    }
}

enum class TalkMode {
    /** `/v1/voice/live`: the server hears and speaks; barge-in. */
    LIVE,

    /** The phone recognises speech and speaks; the text goes through `/v1/ask/stream`. */
    PHONE,

    /** Typing only. */
    TEXT,
}

/** A conversation the talk screen drives: a live call, or the phone's own speech and typing. */
interface Conversation {
    val ui: StateFlow<CallUi>
    val mode: TalkMode

    /** Send a typed turn. [done] gets null once Ira has it, or what went wrong (keep the text). */
    fun send(text: String, done: (String?) -> Unit)

    /** The microphone on (the talk button). */
    fun startListening()

    fun stopIra()

    fun answer(yes: Boolean)

    fun dismissAction()

    fun note(text: String)

    fun end(reason: String? = null)
}
