package io.github.helloupendra.ira.core

import java.io.IOException
import java.net.URI
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/**
 * Pairing: trade the one-time code from the Devices page for this phone's own token.
 *
 * The same exchange as the Mac companion (`clients/mac/ira_mac/pair.py`): someone pastes
 * the pairing link (`https://ira.example.com/pair#code=ABCD-EFGH`), scans its QR code, or
 * types the server and the code; the app asks `POST /v1/devices/pair` and keeps the token
 * it gets in the Android Keystore. A code works once, within 10 minutes.
 */
object Pairing {
    const val KIND = "android"

    private val LINK = Regex("^(https?://[^#\\s]+?)/pair#code=([A-Za-z0-9-]{8,20})$")
    private val CODE = Regex("^[A-Za-z0-9-]{8,20}$")
    private val LOCAL_HOSTS = setOf("127.0.0.1", "localhost", "::1", "[::1]")

    /** (server, code) from a pasted link, or from a typed code and the server given. */
    fun parse(entry: String, server: String?): Pair<String, String> {
        val text = entry.trim()
        LINK.matchEntire(text)?.let { return it.groupValues[1].trimEnd('/') to it.groupValues[2] }
        if (CODE.matches(text)) {
            if (server.isNullOrBlank()) throw PairError("say which server this code is for")
            return server.trim().trimEnd('/') to text
        }
        throw PairError("paste the pairing link or type the 8-character code")
    }

    /** The server address, checked: https, or http only to this phone itself. */
    fun checkServer(server: String): String {
        val uri =
            try {
                URI(server.trim())
            } catch (_: Exception) {
                throw PairError("the server address must start with http:// or https://")
            }
        val scheme = uri.scheme?.lowercase()
        if ((scheme != "http" && scheme != "https") || uri.host.isNullOrEmpty()) {
            throw PairError("the server address must start with http:// or https://")
        }
        if (scheme == "http" && uri.host.lowercase() !in LOCAL_HOSTS) {
            throw PairError("use https:// for a server on another machine")
        }
        return server.trim().trimEnd('/')
    }

    fun requestBody(code: String): String =
        buildJsonObject {
            put("code", JsonPrimitive(code))
            put("kind", JsonPrimitive(KIND))
        }.toString()

    /** Cloudflare answers 403 to generic library user agents, so the app names itself. */
    fun userAgent(version: String): String = "ira-android/$version"

    /** Ask the server; [post] does the HTTP (OkHttp in the app, a fake in tests). */
    fun exchange(server: String, code: String, version: String, post: HttpPost): Paired {
        val base = checkServer(server)
        val reply =
            try {
                post.post(
                    "$base/v1/devices/pair",
                    requestBody(code),
                    mapOf("Content-Type" to "application/json", "User-Agent" to userAgent(version)),
                )
            } catch (exc: IOException) {
                throw PairError("could not reach $base: ${exc.message ?: exc.javaClass.simpleName}")
            }
        when (reply.status) {
            in 200..299 -> Unit
            410 -> throw PairError("that code is used, expired or mistyped; make a new one")
            429 -> throw PairError("too many wrong codes; wait 15 minutes")
            else -> throw PairError("the server answered HTTP ${reply.status}")
        }
        return parseReply(base, reply.body)
    }

    fun parseReply(server: String, body: String): Paired {
        val data = parseObject(body) ?: throw PairError("$server did not answer like an Ira server")
        val token = data.string("token")
        val deviceId = data.int("device_id")
        if (token.isNullOrEmpty() || deviceId == null) {
            throw PairError("the server's answer did not hold a device token")
        }
        return Paired(
            server = server,
            token = token,
            deviceId = deviceId,
            label = data.string("label")?.takeIf { it.isNotBlank() } ?: "My Android phone",
            skills = data.strings("skills"),
            assistant = data.string("name")?.takeIf { it.isNotBlank() } ?: "Ira",
            websocket = data.string("websocket")?.takeIf { it.startsWith("/") } ?: "/v1/devices/ws",
        )
    }

    /** `https://host/x` to `wss://host/x`, for the WebSockets on the same server. */
    fun websocketUrl(server: String, path: String): String {
        val base = server.trimEnd('/')
        val ws =
            when {
                base.startsWith("https://") -> "wss://" + base.removePrefix("https://")
                base.startsWith("http://") -> "ws://" + base.removePrefix("http://")
                else -> base
            }
        return ws + path
    }
}

class PairError(message: String) : Exception(message)

data class Paired(
    val server: String,
    val token: String,
    val deviceId: Int,
    val label: String,
    val skills: List<String>,
    val assistant: String,
    val websocket: String,
) {
    override fun toString(): String = "Paired(server=$server, deviceId=$deviceId, label=$label)"
}

data class HttpReply(val status: Int, val body: String)

fun interface HttpPost {
    @Throws(IOException::class)
    fun post(url: String, body: String, headers: Map<String, String>): HttpReply
}
