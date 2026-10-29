package io.github.helloupendra.ira.net

import android.util.Log
import io.github.helloupendra.ira.BuildConfig
import io.github.helloupendra.ira.core.HttpPost
import io.github.helloupendra.ira.core.HttpReply
import io.github.helloupendra.ira.core.Pairing
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.util.concurrent.TimeUnit
import okhttp3.MediaType
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSink
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

    /** POST JSON with the device token. */
    @Throws(IOException::class)
    fun postJson(url: String, token: String, json: String): HttpReply =
        post.post(url, json, mapOf("Content-Type" to "application/json", "Authorization" to "Bearer $token"))

    /** DELETE with the device token; the HTTP status. */
    @Throws(IOException::class)
    fun delete(url: String, token: String): Int {
        val request = Request.Builder().url(url).header("Authorization", "Bearer $token").header("User-Agent", userAgent).delete().build()
        return rest.newCall(request).execute().use { it.code }
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

    /**
     * Send one file to Drop (`POST /v1/me/drop`, multipart), read from [open] as it goes, so a
     * large one never sits in memory; [progress] hears 0 to 1. Blocking: call it off the main
     * thread. [length] is -1 when unknown.
     */
    @Throws(IOException::class)
    fun upload(url: String, token: String, name: String, mime: String?, length: Long, caption: String?, open: () -> InputStream, progress: (Float) -> Unit): HttpReply {
        val file =
            object : RequestBody() {
                override fun contentType(): MediaType? = (mime ?: "application/octet-stream").toMediaTypeOrNull()

                override fun contentLength(): Long = length

                override fun writeTo(sink: BufferedSink) {
                    open().use { input ->
                        val buffer = ByteArray(64 * 1024)
                        var sent = 0L
                        while (true) {
                            val read = input.read(buffer)
                            if (read < 0) break
                            sink.write(buffer, 0, read)
                            sent += read
                            if (length > 0) progress((sent.toFloat() / length).coerceAtMost(1f))
                        }
                    }
                }
            }
        val body =
            MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .apply { if (!caption.isNullOrBlank()) addFormDataPart("text", caption) }
                .addFormDataPart("file", name, file)
                .build()
        val request =
            Request.Builder().url(url)
                .header("Authorization", "Bearer $token")
                .header("User-Agent", userAgent)
                .post(body)
                .build()
        return transfers.newCall(request).execute().use { HttpReply(it.code, it.body.string()) }
    }

    /** GET a file into [out] as it comes; the HTTP status. Blocking: call it off the main thread. */
    @Throws(IOException::class)
    fun download(url: String, token: String, out: OutputStream): Int {
        val request = Request.Builder().url(url).header("Authorization", "Bearer $token").header("User-Agent", userAgent).build()
        transfers.newCall(request).execute().use { response ->
            if (!response.isSuccessful) return response.code
            response.body.byteStream().use { it.copyTo(out, 64 * 1024) }
            return response.code
        }
    }

    /** Files up to 95 MB, over a phone's connection: minutes, not seconds. */
    private val transfers: OkHttpClient by lazy {
        client.newBuilder().readTimeout(120, TimeUnit.SECONDS).writeTimeout(120, TimeUnit.SECONDS).build()
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
