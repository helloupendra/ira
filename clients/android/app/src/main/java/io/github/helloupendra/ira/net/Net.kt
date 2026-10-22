package io.github.helloupendra.ira.net

import android.util.Log
import io.github.helloupendra.ira.BuildConfig
import io.github.helloupendra.ira.core.HttpPost
import io.github.helloupendra.ira.core.HttpReply
import io.github.helloupendra.ira.core.Pairing
import java.io.IOException
import java.util.concurrent.TimeUnit
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.WebSocket
import okhttp3.WebSocketListener

/** One HTTP client for the app: pairing, and the two WebSockets. */
object Net {
    val client: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.SECONDS) // WebSockets: the protocols ping on their own
            .writeTimeout(20, TimeUnit.SECONDS)
            .build()
    }

    /** Plain requests (pairing, info, confirm, report, speech): an answer within 30 seconds. */
    private val rest: OkHttpClient by lazy { client.newBuilder().readTimeout(30, TimeUnit.SECONDS).build() }

    val userAgent: String
        get() = Pairing.userAgent(BuildConfig.VERSION_NAME)

    val post: HttpPost =
        HttpPost { url, body, headers ->
            val request =
                Request.Builder()
                    .url(url)
                    .post(body.toRequestBody("application/json".toMediaType()))
                    .apply { headers.forEach { (k, v) -> header(k, v) } }
                    .build()
            rest.newCall(request).execute().use { HttpReply(it.code, it.body.string()) }
        }

    /** GET with the device token. Blocking: call it off the main thread. */
    @Throws(IOException::class)
    fun get(url: String, token: String): HttpReply {
        val request = Request.Builder().url(url).header("Authorization", "Bearer $token").header("User-Agent", userAgent).build()
        return rest.newCall(request).execute().use { HttpReply(it.code, it.body.string()) }
    }

    /** POST JSON with the device token; the response body as bytes (MP3 from /v1/voice/speak). */
    @Throws(IOException::class)
    fun postForBytes(url: String, token: String, json: String): Pair<Int, ByteArray> {
        val request =
            Request.Builder().url(url)
                .header("Authorization", "Bearer $token")
                .header("User-Agent", userAgent)
                .post(json.toRequestBody("application/json".toMediaType()))
                .build()
        return rest.newCall(request).execute().use { it.code to it.body.bytes() }
    }

    /**
     * POST JSON and read the answer line by line as it streams (server-sent events). Returns
     * the HTTP status; [onLine] sees each line of a 2xx answer. Blocking: call it off the main
     * thread. The call can be cancelled through [onCall].
     */
    @Throws(IOException::class)
    fun streamLines(url: String, token: String, json: String, onCall: (okhttp3.Call) -> Unit, onLine: (String) -> Unit): Int {
        val request =
            Request.Builder().url(url)
                .header("Authorization", "Bearer $token")
                .header("User-Agent", userAgent)
                .header("Accept", "text/event-stream")
                .post(json.toRequestBody("application/json".toMediaType()))
                .build()
        val call = streaming.newCall(request)
        onCall(call)
        call.execute().use { response ->
            if (!response.isSuccessful) return response.code
            val source = response.body.source()
            while (true) {
                val line = source.readUtf8Line() ?: break
                onLine(line)
            }
            return response.code
        }
    }

    /** A model and its tools can take a while between events: two minutes at most. */
    private val streaming: OkHttpClient by lazy { client.newBuilder().readTimeout(120, TimeUnit.SECONDS).build() }

    fun openWebSocket(url: String, token: String, listener: WebSocketListener): WebSocket {
        val request =
            Request.Builder()
                .url(url)
                .header("Authorization", "Bearer $token")
                .header("User-Agent", userAgent)
                .build()
        return client.newWebSocket(request, listener)
    }
}

/**
 * The app's log: what happened, never what was said. No transcript, no message text, no
 * contact, number, notification or tool argument is ever passed here.
 */
object IraLog {
    private const val TAG = "Ira"

    fun info(event: String) {
        Log.i(TAG, event)
    }

    fun warn(event: String, error: Throwable? = null) {
        // The exception's class only: messages can echo content back.
        Log.w(TAG, if (error == null) event else "$event (${error.javaClass.simpleName})")
    }
}
