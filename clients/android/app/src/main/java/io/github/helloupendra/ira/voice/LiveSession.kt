package io.github.helloupendra.ira.voice

import android.content.Context
import android.os.Handler
import android.os.Looper
import io.github.helloupendra.ira.BuildConfig
import io.github.helloupendra.ira.core.ActionCard
import io.github.helloupendra.ira.core.Backoff
import io.github.helloupendra.ira.core.CallMachine
import io.github.helloupendra.ira.core.EnergyVad
import io.github.helloupendra.ira.core.Live
import io.github.helloupendra.ira.core.LiveProtocol
import io.github.helloupendra.ira.core.Pairing
import io.github.helloupendra.ira.net.IraLog
import io.github.helloupendra.ira.net.Net
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString

/** What the talk screen shows. Kept in memory only, for this call. */
data class CallUi(
    val status: CallStatus = CallStatus.Off,
    val assistant: String = "Ira",
    val caption: String = "",
    val lines: List<Line> = emptyList(),
    val action: ActionCard? = null,
    val notice: String? = null,
    val level: Float = 0f,
    /** The microphone is on. */
    val listening: Boolean = false,
) {
    data class Line(val turn: Int, val fromIra: Boolean, val text: String, val stopped: Boolean = false)
}

enum class CallStatus { Off, Connecting, Listening, Hearing, Thinking, Speaking, Reconnecting, Ended }

/**
 * One live call with Ira over `/v1/voice/live` (protocol 1), on the main thread.
 *
 * The microphone runs only during the call; the voice detector decides what is speech,
 * and only speech (with its short lead-in and the end-of-speech quiet) is sent. Ira's
 * sentences play as they arrive. When the person speaks over Ira, she stops at once.
 */
class LiveSession(
    private val context: Context,
    private val server: String,
    private val token: () -> String?,
    private var conversationId: String?,
    listen: Boolean,
    private val onConversation: (String) -> Unit,
    private val onEnded: (String?) -> Unit,
) : SentencePlayer.Listener {
    private val main = Handler(Looper.getMainLooper())
    private val state = MutableStateFlow(CallUi(status = CallStatus.Connecting))
    val ui: StateFlow<CallUi> = state

    private var machine = CallMachine()
    private val vad = EnergyVad()
    private val mic = MicCapture(context, ::onMicFrame)
    private val player = SentencePlayer(context, this)
    private val backoff = Backoff()
    private var socket: WebSocket? = null
    private var ready = false
    private var ended = false
    private var generation = 0

    @Volatile
    private var replying = false

    @Volatile
    private var listening = false

    /** The person wants the microphone on (a voice call), not only typing. */
    var listenWanted: Boolean = listen
        private set

    private val idle = Runnable { onQuiet() }

    fun start() {
        connect()
    }

    /** Turn the microphone on for this call (the talk button after typing). */
    fun startListening() {
        listenWanted = true
        if (ready && !listening) {
            listening = mic.start()
            if (!listening) state.update { it.copy(notice = "The microphone is not available.") }
        }
        state.update { it.copy(listening = listening) }
    }

    /** A typed turn, in the same conversation. */
    fun type(text: String) {
        apply(machine.typed(text))
    }

    /** The stop button: Ira stops talking and stops this answer. */
    fun stopIra() {
        apply(machine.stop())
        state.update { it.copy(status = statusOf(machine.phase)) }
    }

    /** A tap on a Tier 2 card: the same short yes or no the server listens for. */
    fun answer(yes: Boolean) {
        state.update { it.copy(action = null) }
        type(if (yes) "yes" else "no")
    }

    fun dismissAction() {
        state.update { it.copy(action = null) }
    }

    /** Hang up on purpose. */
    fun end(reason: String? = null) {
        if (ended) return
        ended = true
        main.removeCallbacksAndMessages(null)
        listening = false
        mic.stop()
        player.release()
        socket?.let {
            it.send(LiveProtocol.bye())
            it.close(1000, "bye")
        }
        socket = null
        state.update { it.copy(status = CallStatus.Ended, notice = reason ?: it.notice, level = 0f, listening = false) }
        onEnded(reason)
    }

    // The connection.

    private fun connect() {
        val bearer = token()
        if (bearer == null) {
            end("This phone is not paired with Ira. Pair it again.")
            return
        }
        val mine = ++generation
        ready = false
        machine = CallMachine()
        state.update { it.copy(status = if (backoff.attempt == 0) CallStatus.Connecting else CallStatus.Reconnecting) }
        val url = Pairing.websocketUrl(server, LiveProtocol.PATH)
        socket =
            Net.openWebSocket(
                url,
                bearer,
                object : WebSocketListener() {
                    override fun onOpen(webSocket: WebSocket, response: Response) {
                        main.post { if (mine == generation) opened(webSocket) }
                    }

                    override fun onMessage(webSocket: WebSocket, text: String) {
                        main.post { if (mine == generation) onText(text) }
                    }

                    override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                        val data = bytes.toByteArray()
                        main.post { if (mine == generation) apply(machine.onBinary(data)) }
                    }

                    override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                        webSocket.close(1000, null)
                        main.post { if (mine == generation) dropped(code) }
                    }

                    override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                        IraLog.warn("live: connection failed", t)
                        main.post { if (mine == generation) dropped(response?.code ?: 0) }
                    }
                },
            )
    }

    private fun opened(webSocket: WebSocket) {
        IraLog.info("live: connected")
        backoff.connected(nowMs() / 1000)
        webSocket.send(LiveProtocol.start("ira-android/${BuildConfig.VERSION_NAME}", conversationId))
    }

    private fun dropped(code: Int) {
        if (ended) return
        listening = false
        mic.stop()
        player.stop()
        socket = null
        state.update { it.copy(listening = false) }
        if (Backoff.isRefusal(code)) {
            end("This phone is no longer paired with Ira. Pair it again.")
            return
        }
        val wait = backoff.next(nowMs() / 1000)
        IraLog.info("live: reconnecting in ${wait.toInt()} s")
        state.update { it.copy(status = CallStatus.Reconnecting) }
        main.postDelayed({ if (!ended) connect() }, (wait * 1000).toLong())
    }

    private fun onText(text: String) {
        val message = LiveProtocol.parse(text)
        apply(machine.onServer(message, nowMs()))
        when (message) {
            is Live.Ready -> {
                ready = true
                conversationId = message.conversationId
                onConversation(message.conversationId)
                state.update { it.copy(status = CallStatus.Listening, assistant = message.assistant, notice = null) }
                if (listenWanted) {
                    listening = mic.start()
                    if (!listening) state.update { it.copy(notice = "The microphone is not available.") }
                }
                state.update { it.copy(listening = listening) }
                quietTimer()
            }
            is Live.Partial -> state.update { it.copy(caption = message.text) }
            is Live.Heard ->
                state.update {
                    it.copy(caption = "", lines = (it.lines + CallUi.Line(message.turn, false, message.text)).takeLast(MAX_LINES))
                }
            is Live.Delta -> state.update { it.copy(lines = upsertIra(it.lines, message.turn) { old -> old + message.text }) }
            is Live.Done -> {
                state.update { it.copy(lines = upsertIra(it.lines, message.turn) { old -> message.text.ifBlank { old } }) }
                quietTimer()
            }
            is Live.Interrupted ->
                state.update { s -> s.copy(lines = s.lines.map { if (it.fromIra && it.turn == message.turn) it.copy(stopped = true) else it }) }
            is Live.Error -> if (!message.fatal) state.update { it.copy(notice = message.message) }
            else -> Unit
        }
        state.update { it.copy(status = statusOf(machine.phase)) }
    }

    private fun apply(effects: List<CallMachine.Effect>) {
        for (effect in effects) {
            when (effect) {
                is CallMachine.Effect.Send -> socket?.send(effect.json)
                is CallMachine.Effect.StopPlayback -> player.stop()
                is CallMachine.Effect.Play -> player.enqueue(effect.sentences)
                is CallMachine.Effect.ShowAction -> state.update { it.copy(action = effect.card) }
                is CallMachine.Effect.End -> end(effect.reason)
            }
        }
        replying = machine.playing
    }

    // The microphone (its own thread) and the voice detector.

    private fun onMicFrame(samples: ShortArray, at: Double) {
        vad.replying = replying
        val outputs = vad.process(samples, at)
        val level = vad.level
        main.post {
            if (ended || !ready) return@post
            for (output in outputs) {
                when (output) {
                    is EnergyVad.Output.SpeechStart -> {
                        main.removeCallbacks(idle)
                        apply(machine.onSpeechStart(output.at))
                    }
                    is EnergyVad.Output.Audio -> {
                        for (chunk in LiveProtocol.chunks(output.pcm)) socket?.send(chunk.toByteString())
                    }
                    is EnergyVad.Output.SpeechEnd -> {
                        apply(machine.onSpeechEnd(output.at))
                        quietTimer()
                    }
                }
            }
            state.update { it.copy(level = level, status = statusOf(machine.phase)) }
        }
    }

    // The player.

    override fun onSentenceStarted(turn: Int, seq: Int) {
        main.removeCallbacks(idle)
        apply(machine.onSentenceStarted(turn, nowMs()))
        state.update { it.copy(status = statusOf(machine.phase)) }
    }

    override fun onSentenceFinished(turn: Int, seq: Int) {
        machine.onSentenceFinished()
        replying = machine.playing
        state.update { it.copy(status = statusOf(machine.phase)) }
        quietTimer()
    }

    /** Two quiet minutes with nothing playing end the call: the microphone is not left on. */
    private fun onQuiet() {
        if (machine.phase == CallMachine.Phase.Listening && !machine.playing) {
            end("The call ended after two quiet minutes.")
        } else {
            quietTimer()
        }
    }

    private fun quietTimer() {
        main.removeCallbacks(idle)
        main.postDelayed(idle, QUIET_MS)
    }

    private fun statusOf(phase: CallMachine.Phase): CallStatus =
        if (ended) {
            CallStatus.Ended
        } else {
            when (phase) {
                CallMachine.Phase.Connecting -> CallStatus.Connecting
                CallMachine.Phase.Listening -> CallStatus.Listening
                CallMachine.Phase.UserSpeaking -> CallStatus.Hearing
                CallMachine.Phase.Thinking -> CallStatus.Thinking
                CallMachine.Phase.Speaking -> CallStatus.Speaking
            }
        }

    private fun upsertIra(lines: List<CallUi.Line>, turn: Int, change: (String) -> String): List<CallUi.Line> {
        val index = lines.indexOfLast { it.fromIra && it.turn == turn }
        val out = lines.toMutableList()
        if (index >= 0) out[index] = out[index].copy(text = change(out[index].text)) else out += CallUi.Line(turn, true, change(""))
        return out.takeLast(MAX_LINES)
    }

    private companion object {
        const val MAX_LINES = 40
        const val QUIET_MS = 120_000L
    }
}
