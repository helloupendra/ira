package io.github.helloupendra.ira.net

import android.util.Log
import io.github.helloupendra.ira.BuildConfig
import io.github.helloupendra.ira.core.HttpPost
import io.github.helloupendra.ira.core.HttpReply
import io.github.helloupendra.ira.core.Pairing
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
            client.newCall(request).execute().use { HttpReply(it.code, it.body.string()) }
        }

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
