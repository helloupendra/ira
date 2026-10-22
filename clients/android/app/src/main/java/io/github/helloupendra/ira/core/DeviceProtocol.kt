package io.github.helloupendra.ira.core

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/**
 * The device WebSocket (`docs/devices.md`): `GET /v1/devices/ws` with the device token.
 * The phone says hello with the tools it offers, answers each `call` with a `result`
 * carrying the same id, and pings every 30 seconds.
 */
object DeviceProtocol {
    const val PATH = "/v1/devices/ws"
    const val PING_SECONDS = 30.0
    const val SILENCE_SECONDS = 90.0
    const val CALL_SECONDS = 25.0
    const val MAX_IN_FLIGHT = 4
    const val MAX_TOOLS = 30
    const val MAX_FRAME_BYTES = 1024 * 1024

    private val TOOL_NAME = Regex("^[a-z][a-z0-9_]{2,40}$")
    private val SKILL_NAME = Regex("^[a-z][a-z0-9_]{1,30}$")

    fun hello(label: String, version: String, tools: List<ToolSpec>): String {
        require(tools.size <= MAX_TOOLS) { "a device offers $MAX_TOOLS tools at most" }
        return buildJsonObject {
            put("type", JsonPrimitive("hello"))
            put("kind", JsonPrimitive(Pairing.KIND))
            put("label", JsonPrimitive(label))
            put("version", JsonPrimitive(version))
            put("tools", JsonArray(tools.map { it.toJson() }))
        }.toString()
    }

    fun result(id: String, content: JsonElement): String =
        buildJsonObject {
            put("type", JsonPrimitive("result"))
            put("id", JsonPrimitive(id))
            put("ok", JsonPrimitive(true))
            put("content", content)
        }.toString()

    fun failure(id: String, error: String): String =
        buildJsonObject {
            put("type", JsonPrimitive("result"))
            put("id", JsonPrimitive(id))
            put("ok", JsonPrimitive(false))
            put("error", JsonPrimitive(error.take(500)))
        }.toString()

    fun ping(): String = """{"type":"ping"}"""

    fun pong(): String = """{"type":"pong"}"""

    fun parse(text: String): DeviceFrame {
        val m = parseObject(text) ?: return DeviceFrame.Unknown("not a JSON object")
        return when (val type = m.string("type")) {
            "welcome" ->
                DeviceFrame.Welcome(
                    deviceId = m.int("deviceId"),
                    label = m.string("label").orEmpty(),
                    skills = m.strings("skills"),
                    assistant = m.string("assistant") ?: "Ira",
                    wakePhrase = m.string("wakePhrase"),
                )
            "call" -> {
                val id = m.string("id")
                val tool = m.string("tool")
                if (id.isNullOrEmpty() || tool.isNullOrEmpty()) {
                    DeviceFrame.Unknown("a call without an id or a tool")
                } else {
                    DeviceFrame.Call(id, tool, m.obj("args") ?: JsonObject(emptyMap()))
                }
            }
            "skills" -> DeviceFrame.Skills(m.strings("skills"))
            "event" ->
                DeviceFrame.Event(
                    event = m.string("event").orEmpty(),
                    title = m.string("title").orEmpty(),
                    text = m.string("text").orEmpty(),
                )
            "ping" -> DeviceFrame.Ping
            "pong" -> DeviceFrame.Pong
            "error" -> DeviceFrame.Error(m.string("error") ?: m.string("message") ?: "error")
            else -> DeviceFrame.Unknown("unknown type '${type ?: ""}'")
        }
    }

    /** The rules the server checks in a hello, checked here first (and in tests). */
    fun problems(tools: List<ToolSpec>): List<String> {
        val out = ArrayList<String>()
        if (tools.size > MAX_TOOLS) out += "more than $MAX_TOOLS tools"
        val seen = HashSet<String>()
        for (tool in tools) {
            if (!TOOL_NAME.matches(tool.name)) out += "bad tool name ${tool.name}"
            if (!seen.add(tool.name)) out += "${tool.name} listed twice"
            if (!SKILL_NAME.matches(tool.skill)) out += "${tool.name}: bad skill ${tool.skill}"
            if (tool.tier !in 0..3) out += "${tool.name}: bad tier ${tool.tier}"
            if (tool.description.isBlank() || tool.description.length > 1000) out += "${tool.name}: description"
            if (tool.parameters.toString().length > 8 * 1024) out += "${tool.name}: parameters over 8 KB"
            if (tool.parameters["type"] != JsonPrimitive("object")) out += "${tool.name}: parameters not an object"
        }
        return out
    }
}

sealed interface DeviceFrame {
    data class Welcome(
        val deviceId: Int?,
        val label: String,
        val skills: List<String>,
        val assistant: String,
        val wakePhrase: String?,
    ) : DeviceFrame

    data class Call(val id: String, val tool: String, val args: JsonObject) : DeviceFrame

    /** The skills switched on for this device changed. */
    data class Skills(val skills: List<String>) : DeviceFrame

    /** An event for this phone's person: shown as a notification. */
    data class Event(val event: String, val title: String, val text: String) : DeviceFrame

    data object Ping : DeviceFrame

    data object Pong : DeviceFrame

    data class Error(val message: String) : DeviceFrame

    data class Unknown(val why: String) : DeviceFrame
}
