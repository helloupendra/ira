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

/** What the talk screen shows besides the transcript. Kept in memory only. */
data class CallUi(
    val status: CallStatus = CallStatus.Off,
    val assistant: String = "Ira",
    val caption: String = "",
    val action: ActionCard? = null,
    val notice: String? = null,
    val level: Float = 0f,
    /** The microphone is on. */
    val listening: Boolean = false,
    val mode: TalkMode = TalkMode.TEXT,
)

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
    private val transcript: Transcript,
    private val onConversation: (String) -> Unit,
    /** The call ended: why (null when the person hung up), and whether live calls cannot work here. */
    private val onEnded: (reason: String?, unavailable: Boolean) -> Unit,
) : SentencePlayer.Listener, Conversation {
    private val main = Handler(Looper.getMainLooper())
    private val state = MutableStateFlow(CallUi(status = CallStatus.Connecting, mode = TalkMode.LIVE))
    override val ui: StateFlow<CallUi> = state
    override val mode = TalkMode.LIVE

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

    private val idle = Runnable { onQuiet() }

    fun start() {
        connect()
    }

    /** True while the call is connected: a typed turn can go over it. */
    val connected: Boolean
        get() = ready && socket != null && !ended

    /** Turn the microphone on again (it is on from the start of a call). */
    override fun startListening() {
        if (ready && !listening) {
            listening = mic.start()
            if (!listening) state.update { it.copy(notice = MIC_BUSY) }
        }
        state.update { it.copy(listening = listening) }
    }

    /** A typed turn over the call; the server shows it back as `heard`. */
    override fun send(text: String, done: (String?) -> Unit) {
        if (!connected) return done("The live call is not connected. Send it again in a moment.")
        done(if (apply(machine.typed(text))) null else "The live call dropped. Send it again in a moment.")
    }

    /** The stop button: Ira stops talking and stops this answer. */
    override fun stopIra() {
        apply(machine.stop())
        state.update { it.copy(status = statusOf(machine.phase)) }
    }

    /** A tap on a Tier 2 card: the same short yes or no the server listens for. */
    override fun answer(yes: Boolean) {
        state.update { it.copy(action = null) }
        send(if (yes) "yes" else "no") { error -> if (error != null) state.update { it.copy(notice = error) } }
    }

    override fun dismissAction() {
        state.update { it.copy(action = null) }
    }

    /** A line from the app itself in the transcript (an action confirmed with the PIN). */
    override fun note(text: String) {
        transcript.add(Transcript.Line("note:${nowMs()}", true, text))
    }

    /** Hang up on purpose. */
    override fun end(reason: String?) {
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
        val unavailable = reason != null && LIVE_UNAVAILABLE.any { reason.contains(it, ignoreCase = true) }
        val shown = if (unavailable) NO_LIVE else reason
        state.update { it.copy(status = CallStatus.Ended, notice = shown ?: it.notice, level = 0f, listening = false) }
        onEnded(shown, unavailable)
    }

    // The connection.

    private fun connect() {
        val bearer = token()
        if (bearer == null) {
            end("This phone is not paired with an Ira. Pair it from Settings.")
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
            end("Your Ira no longer accepts this phone: it was removed on Your devices. Pair it again from Settings.")
            return
        }
        val wait = backoff.next(nowMs() / 1000)
        IraLog.info("live: reconnecting in ${wait.toInt()} s")
        val host = server.removePrefix("https://").removePrefix("http://")
        state.update {
            it.copy(
                status = CallStatus.Reconnecting,
                notice = "Can't reach your Ira at $host. Trying again in ${maxOf(1, wait.toInt())} s; check that the phone is online and your Ira is running.",
            )
        }
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
                listening = mic.start()
                if (!listening) state.update { it.copy(notice = MIC_BUSY) }
                state.update { it.copy(listening = listening) }
                quietTimer()
            }
            is Live.Partial -> state.update { it.copy(caption = message.text) }
            is Live.Heard -> {
                state.update { it.copy(caption = "") }
                transcript.add(Transcript.Line(key(message.turn) + ":you", false, message.text))
            }
            is Live.Delta -> transcript.ira(key(message.turn)) { it.copy(text = it.text + message.text) }
            is Live.Done -> {
                transcript.ira(key(message.turn)) { it.copy(text = message.text.ifBlank { it.text }, messageId = message.messageId) }
                quietTimer()
            }
            is Live.Interrupted -> transcript.stopped(key(message.turn))
            is Live.Error -> if (!message.fatal) state.update { it.copy(notice = message.message) }
            else -> Unit
        }
        state.update { it.copy(status = statusOf(machine.phase)) }
    }

    /** Do what the machine says; false when a frame for the server could not be sent. */
    private fun apply(effects: List<CallMachine.Effect>): Boolean {
        var sent = true
        for (effect in effects) {
            when (effect) {
                is CallMachine.Effect.Send -> sent = (socket?.send(effect.json) == true) && sent
                is CallMachine.Effect.StopPlayback -> player.stop()
                is CallMachine.Effect.Play -> player.enqueue(effect.sentences)
                is CallMachine.Effect.ShowAction -> state.update { it.copy(action = effect.card) }
                is CallMachine.Effect.End -> end(effect.reason)
            }
        }
        replying = machine.playing
        return sent
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

    /** Turns restart at 1 on each connection: the connection's number keeps lines apart. */
    private fun key(turn: Int) = "live$generation:$turn"

    companion object {
        const val MIC_BUSY =
            "The microphone is busy or not allowed. Close other apps that use it, or allow the microphone for Ira in Android's settings."
        const val NO_LIVE = "Live calls need your Ira to have speech set up. Using the phone's own speech recognition instead."

        /** The server's reasons that mean no live call can work here (`channels/live.py`). */
        private val LIVE_UNAVAILABLE = listOf("speech-to-text", "text-to-speech", "talk to Ira by voice")
        private const val QUIET_MS = 120_000L
    }
}
