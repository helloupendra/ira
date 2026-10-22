package io.github.helloupendra.ira.device

import android.os.Handler
import android.os.Looper
import io.github.helloupendra.ira.BuildConfig
import io.github.helloupendra.ira.core.Backoff
import io.github.helloupendra.ira.core.DeviceFrame
import io.github.helloupendra.ira.core.DeviceProtocol
import io.github.helloupendra.ira.core.Pairing
import io.github.helloupendra.ira.core.ToolFailure
import io.github.helloupendra.ira.core.ToolSpec
import io.github.helloupendra.ira.net.IraLog
import io.github.helloupendra.ira.net.Net
import io.github.helloupendra.ira.voice.nowMs
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

/** Runs this phone's tools when Ira calls them. */
interface ToolRunner {
    val tools: List<ToolSpec>

    /** Run one tool. A [ToolFailure]'s message goes back to Ira as the error. */
    suspend fun run(name: String, args: JsonObject): JsonElement
}

sealed interface LinkState {
    data object Off : LinkState

    data object Connecting : LinkState

    data class Connected(val skills: List<String>) : LinkState

    data class Waiting(val seconds: Int) : LinkState

    /** The server refused this phone's token: it was removed, or never paired. */
    data object Refused : LinkState
}

/**
 * Holds this phone's device WebSocket (`/v1/devices/ws`), the same way the Mac app does:
 *
 * - says hello with its tools (kind `android`), then answers each `call` with a `result`
 *   carrying the same id, several at once (4 at most), each within 25 seconds;
 * - pings every 30 seconds, and reconnects when it hears nothing for 90;
 * - reconnects with a growing delay; after a refused token, every 5 minutes;
 * - shows the person's events (a task finished) as notifications.
 */
class DeviceLink(
    private val server: String,
    private val path: String,
    private val token: () -> String?,
    private val label: String,
    private val runner: ToolRunner,
    private val onSkills: (List<String>) -> Unit,
    private val onEvent: (DeviceFrame.Event) -> Unit,
) {
    private val main = Handler(Looper.getMainLooper())
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val backoff = Backoff()
    private val inFlight = AtomicInteger(0)
    private val state = MutableStateFlow<LinkState>(LinkState.Off)
    val status: StateFlow<LinkState> = state

    private var socket: WebSocket? = null
    private var running = false
    private var generation = 0
    private var lastHeard = 0.0

    private val ticker =
        object : Runnable {
            override fun run() {
                if (!running) return
                val quiet = nowMs() / 1000 - lastHeard
                if (socket != null && quiet > DeviceProtocol.SILENCE_SECONDS) {
                    IraLog.info("device: silent for 90 s, reconnecting")
                    socket?.cancel()
                    dropped(0)
                } else {
                    socket?.send(DeviceProtocol.ping())
                }
                main.postDelayed(this, (DeviceProtocol.PING_SECONDS * 1000).toLong())
            }
        }

    fun start() {
        if (running) return
        running = true
        backoff.reset()
        connect()
        main.postDelayed(ticker, (DeviceProtocol.PING_SECONDS * 1000).toLong())
    }

    fun stop() {
        running = false
        generation++
        main.removeCallbacksAndMessages(null)
        socket?.close(1000, "bye")
        socket = null
        state.value = LinkState.Off
    }

    /** Remove this phone from Ira: the server revokes its token when it hears `bye`. */
    fun unpair(done: () -> Unit) {
        stop()
        val bearer = token() ?: return done()
        Net.openWebSocket(
            Pairing.websocketUrl(server, path),
            bearer,
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    webSocket.send("""{"type":"bye"}""")
                    webSocket.close(1000, "bye")
                    main.post(done)
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    main.post(done)
                }
            },
        )
    }

    fun release() {
        stop()
        scope.cancel()
    }

    private fun connect() {
        if (!running) return
        val bearer = token()
        if (bearer == null) {
            state.value = LinkState.Refused
            return
        }
        val mine = ++generation
        state.value = LinkState.Connecting
        socket =
            Net.openWebSocket(
                Pairing.websocketUrl(server, path),
                bearer,
                object : WebSocketListener() {
                    override fun onOpen(webSocket: WebSocket, response: Response) {
                        main.post {
                            if (mine != generation) return@post
                            lastHeard = nowMs() / 1000
                            webSocket.send(DeviceProtocol.hello(label, BuildConfig.VERSION_NAME, runner.tools))
                        }
                    }

                    override fun onMessage(webSocket: WebSocket, text: String) {
                        main.post { if (mine == generation) onFrame(webSocket, text) }
                    }

                    override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                        webSocket.close(1000, null)
                        main.post { if (mine == generation) dropped(code) }
                    }

                    override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                        IraLog.warn("device: connection failed", t)
                        main.post { if (mine == generation) dropped(response?.code ?: 0) }
                    }
                },
            )
    }

    private fun dropped(code: Int) {
        if (!running) return
        generation++
        socket = null
        val refused = Backoff.isRefusal(code)
        val wait = backoff.next(nowMs() / 1000, refused)
        state.value = if (refused) LinkState.Refused else LinkState.Waiting(wait.toInt())
        main.postDelayed({ connect() }, (wait * 1000).toLong())
    }

    private fun onFrame(webSocket: WebSocket, text: String) {
        lastHeard = nowMs() / 1000
        when (val frame = DeviceProtocol.parse(text)) {
            is DeviceFrame.Welcome -> {
                IraLog.info("device: welcomed")
                backoff.connected(nowMs() / 1000)
                state.value = LinkState.Connected(frame.skills)
                onSkills(frame.skills)
            }
            is DeviceFrame.Skills -> {
                state.value = LinkState.Connected(frame.skills)
                onSkills(frame.skills)
            }
            is DeviceFrame.Call -> call(webSocket, frame)
            is DeviceFrame.Event -> onEvent(frame)
            is DeviceFrame.Ping -> webSocket.send(DeviceProtocol.pong())
            is DeviceFrame.Pong -> Unit
            is DeviceFrame.Error -> IraLog.info("device: the server refused a frame")
            is DeviceFrame.Unknown -> Unit
        }
    }

    private fun call(webSocket: WebSocket, frame: DeviceFrame.Call) {
        if (inFlight.incrementAndGet() > DeviceProtocol.MAX_IN_FLIGHT) {
            inFlight.decrementAndGet()
            webSocket.send(DeviceProtocol.failure(frame.id, "the phone is busy"))
            return
        }
        // Only the tool's name is logged: never its arguments or what it returned.
        IraLog.info("device: call ${frame.tool}")
        scope.launch {
            val reply =
                try {
                    val content =
                        withTimeout(((DeviceProtocol.CALL_SECONDS - 2) * 1000).toLong()) {
                            runner.run(frame.tool, frame.args)
                        }
                    DeviceProtocol.result(frame.id, content)
                } catch (exc: ToolFailure) {
                    DeviceProtocol.failure(frame.id, exc.message ?: "it did not work")
                } catch (exc: kotlinx.coroutines.TimeoutCancellationException) {
                    DeviceProtocol.failure(frame.id, "the phone took too long")
                } catch (exc: Exception) {
                    IraLog.warn("device: ${frame.tool} failed", exc)
                    DeviceProtocol.failure(frame.id, "it did not work on the phone")
                } finally {
                    inFlight.decrementAndGet()
                }
            webSocket.send(reply)
        }
    }
}
