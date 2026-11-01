package io.github.helloupendra.ira.core

import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject

/**
 * "Now", under the greeting of an empty conversation, as on the web: at most a few cards, each
 * real. The newest Drop item of the last day, and the person's devices that are on. A card is
 * left out when there is nothing to show or its source failed; never filler.
 */
object Now {
    const val DEVICES_PATH = "/v1/me/devices"

    enum class Opens { DROP, NOTHING }

    data class Card(val label: String, val value: String, val detail: String, val opens: Opens)

    data class Device(val label: String, val connected: Boolean)

    /** `GET /v1/me/devices`: each device's name and whether it is on now; null when it is not a list. */
    fun devices(body: String): List<Device>? {
        val list =
            try {
                IraJson.parseToJsonElement(body) as? JsonArray
            } catch (_: Exception) {
                null
            } ?: return null
        return list.mapNotNull { element ->
            val o = element as? JsonObject ?: return@mapNotNull null
            val label = o.string("label")?.takeIf { it.isNotBlank() } ?: return@mapNotNull null
            Device(label, o.bool("connected") == true)
        }
    }

    fun cards(
        newest: Drop.Item?,
        devices: List<Device>?,
        now: Instant = Instant.now(),
        zone: ZoneId = ZoneId.systemDefault(),
    ): List<Card> =
        buildList {
            val arrived = newest?.let(Drop::arrived)
            if (newest != null && arrived != null && Duration.between(arrived, now) < Duration.ofDays(1)) {
                val time = arrived.atZone(zone).toLocalTime().format(DateTimeFormatter.ofLocalizedTime(FormatStyle.SHORT))
                add(Card("Drop", Drop.title(newest).ifBlank { "An item" }, "from ${newest.fromLabel.ifBlank { "a device" }} · $time", Opens.DROP))
            }
            if (!devices.isNullOrEmpty()) {
                val on = devices.filter { it.connected }
                val value = if (on.isEmpty()) "None connected" else on.joinToString(" · ") { it.label }
                add(Card("Devices", value, "${on.size} of ${devices.size} on", Opens.NOTHING))
            }
        }

    /** The part of the day the greeting names: "morning", "afternoon" or "evening". */
    fun partOfDay(hour: Int): String = if (hour < 12) "morning" else if (hour < 17) "afternoon" else "evening"
}
