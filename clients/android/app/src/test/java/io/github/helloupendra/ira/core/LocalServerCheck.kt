package io.github.helloupendra.ira.core

import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlin.math.PI
import kotlin.math.sin
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test

/**
 * An opt-in check against a running local Ira (`ira serve` with `voice.stt.type: fake` and
 * `voice.tts.type: fake`), skipped unless these are set:
 *
 *     IRA_TEST_SERVER=http://127.0.0.1:8765
 *     IRA_TEST_PAIRING=ABCD-EFGH        a fresh Android pairing code with the calls skill
 *     IRA_TEST_SESSION=...              a session token of the same person (to ask Ira)
 *
 * It pairs as the app does, says hello with the Play build's tools, answers a real tool
 * call, and holds a live call: a typed turn, a spoken turn, and a barge-in.
 */
class LocalServerCheck {
    private val server = System.getenv("IRA_TEST_SERVER")
    private val code = System.getenv("IRA_TEST_PAIRING")
    private val session = System.getenv("IRA_TEST_SESSION")
    private val client = OkHttpClient.Builder().readTimeout(30, TimeUnit.SECONDS).build()

    private sealed interface Frame {
        data class Text(val text: String) : Frame

        class Binary(val bytes: ByteArray) : Frame

        data class Closed(val code: Int) : Frame
    }

    private fun open(path: String, token: String): Pair<WebSocket, LinkedBlockingQueue<Frame>> {
        val frames = LinkedBlockingQueue<Frame>()
        val request =
            Request.Builder()
                .url(Pairing.websocketUrl(server!!, path))
                .header("Authorization", "Bearer $token")
                .header("User-Agent", Pairing.userAgent("0.1.0"))
                .build()
        val socket =
            client.newWebSocket(
                request,
                object : WebSocketListener() {
                    override fun onMessage(webSocket: WebSocket, text: String) {
                        frames.put(Frame.Text(text))
                    }

                    override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                        frames.put(Frame.Binary(bytes.toByteArray()))
                    }

                    override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                        frames.put(Frame.Closed(code))
                    }

                    override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                        frames.put(Frame.Closed(response?.code ?: -1))
                    }
                },
            )
        return socket to frames
    }

    private fun LinkedBlockingQueue<Frame>.next(seconds: Long = 15): Frame =
        poll(seconds, TimeUnit.SECONDS) ?: throw AssertionError("nothing from the server in $seconds s")

    @Test
    fun `pair, offer the phone's tools, and talk live`() {
        assumeTrue(server != null && code != null && session != null)
        val post =
            HttpPost { url, body, headers ->
                val request =
                    Request.Builder().url(url).post(body.toRequestBody("application/json".toMediaType()))
                        .apply { headers.forEach { (k, v) -> header(k, v) } }.build()
                client.newCall(request).execute().use { HttpReply(it.code, it.body.string()) }
            }

        // 1. Pairing, exactly as the app does it.
        val paired = Pairing.exchange(server!!, code!!, "0.1.0", post)
        assertTrue(paired.token.startsWith("irad_"))
        println("paired as device ${paired.deviceId} with skills ${paired.skills}")

        // 2. The device WebSocket: hello with the Play build's tools, then welcome.
        val (device, deviceFrames) = open(paired.websocket, paired.token)
        device.send(DeviceProtocol.hello("Test phone", "0.1.0", ToolCatalog.forFlavor(Flavor.PLAY)))
        var welcome: DeviceFrame.Welcome? = null
        while (welcome == null) {
            when (val f = deviceFrames.next()) {
                is Frame.Text -> welcome = DeviceProtocol.parse(f.text) as? DeviceFrame.Welcome ?: run {
                    throw AssertionError("expected welcome, got ${f.text}")
                }
                else -> throw AssertionError("device socket: $f")
            }
        }
        println("welcomed: skills ${welcome.skills}")
        assertTrue("calls" in welcome.skills)

        // 3. Ira calls a phone tool: ask through the HTTP API, answer the call here.
        val asker =
            Thread {
                val request =
                    Request.Builder().url("$server/v1/ask")
                        .header("Authorization", "Bearer $session")
                        .post(
                            buildJsonObject { put("text", JsonPrimitive("calls recent: who called?")) }
                                .toString().toRequestBody("application/json".toMediaType()),
                        ).build()
                client.newCall(request).execute().use { println("ask answered ${it.code}: ${it.body.string().take(300)}") }
            }
        asker.start()
        val call = (deviceFrames.next(20) as Frame.Text).let { DeviceProtocol.parse(it.text) }
        println("server called: $call")
        if (call is DeviceFrame.Call) {
            assertEquals("calls_recent", call.tool)
            val content =
                buildJsonObject {
                    put("calls", buildJsonArray { add(buildJsonObject { put("name", JsonPrimitive("Rahul Sharma")); put("number", JsonPrimitive("+919810000000")); put("kind", JsonPrimitive("missed")) }) })
                    put("summary", JsonPrimitive("missed from Rahul Sharma at 10:42"))
                }
            device.send(DeviceProtocol.result(call.id, content))
        }
        asker.join(20_000)

        // 4. A live call with the device token.
        val (live, liveFrames) = open(LiveProtocol.PATH, paired.token)
        live.send(LiveProtocol.start("ira-android/0.1.0", null))
        val machine = CallMachine()
        fun pump(until: (Live) -> Boolean, seconds: Long = 20): List<Live> {
            val seen = ArrayList<Live>()
            while (true) {
                when (val f = liveFrames.next(seconds)) {
                    is Frame.Text -> {
                        val m = LiveProtocol.parse(f.text)
                        seen += m
                        machine.onServer(m, 0.0).filterIsInstance<CallMachine.Effect.Send>().forEach { live.send(it.json) }
                        if (until(m)) return seen
                    }
                    is Frame.Binary -> {
                        val effects = machine.onBinary(f.bytes)
                        effects.filterIsInstance<CallMachine.Effect.Play>().forEach { p ->
                            p.sentences.forEach { println("audio turn ${it.turn} seq ${it.seq}: ${it.mp3.size} bytes, '${it.text}'") }
                        }
                    }
                    is Frame.Closed -> throw AssertionError("live socket closed: ${f.code}")
                }
            }
        }
        val ready = pump({ it is Live.Ready || it is Live.Error }).last()
        assertTrue("ready, not $ready", ready is Live.Ready)
        println("ready: $ready")

        // A typed turn.
        machine.typed("hello Ira").forEach { if (it is CallMachine.Effect.Send) live.send(it.json) }
        val typed = pump({ it is Live.Done || (it is Live.Error && it.fatal) })
        println("typed turn: ${typed.map { it::class.simpleName }}")
        assertNotNull(typed.firstOrNull { it is Live.Heard })

        // Report that answer, as the app's Report button does; someone else's id is refused.
        val answer = typed.filterIsInstance<Live.Done>().single().messageId
        assertNotNull("the done event carries the answer's message_id", answer)
        val reported = Reports.send(server, paired.token, answer!!, "wrong", "a check from the Android tests", post)
        println("report: $reported")
        assertTrue(reported.ok)
        assertTrue(Reports.send(server, paired.token, 999_999, "wrong", null, post).message.contains("no longer"))

        // A spoken turn: speech_start, a second of synthetic voice, speech_end.
        machine.onSpeechStart(1_000.0).forEach { if (it is CallMachine.Effect.Send) live.send(it.json) }
        val tone = ShortArray(16_000) { (sin(2 * PI * 220 * it / 16_000) * 8_000).toInt().toShort() }
        LiveProtocol.chunks(Pcm.toBytes(tone)).forEach { live.send(it.toByteString()) }
        machine.onSpeechEnd(2_000.0).forEach { if (it is CallMachine.Effect.Send) live.send(it.json) }
        val spoken = pump({ it is Live.Done || it is Live.Error })
        println("spoken turn: ${spoken.map { it::class.simpleName }}")
        val heard = spoken.firstOrNull { it is Live.Heard } as Live.Heard?
        assertNotNull("the fake transcript comes back as heard", heard)

        // A barge-in: speak again while the next answer is on its way.
        machine.typed("tell me more").forEach { if (it is CallMachine.Effect.Send) live.send(it.json) }
        pump({ it is Live.Heard })
        val barge = machine.onSpeechStart(5_000.0)
        assertTrue(CallMachine.Effect.StopPlayback in barge)
        barge.forEach { if (it is CallMachine.Effect.Send) live.send(it.json) }
        val after = pump({ it is Live.Interrupted || it is Live.Done })
        println("after barge-in: ${after.map { it::class.simpleName }}")
        machine.onSpeechEnd(5_100.0).forEach { if (it is CallMachine.Effect.Send) live.send(it.json) }

        live.send(LiveProtocol.bye())
        live.close(1000, "bye")
        device.close(1000, "bye")
    }
}
