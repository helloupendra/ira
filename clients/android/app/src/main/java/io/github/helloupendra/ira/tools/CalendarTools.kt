package io.github.helloupendra.ira.tools

import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.provider.CalendarContract
import io.github.helloupendra.ira.core.Args
import io.github.helloupendra.ira.core.ToolFailure
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import kotlinx.serialization.json.JsonElement

/**
 * The calendars on the phone, through Android's own calendar provider: whatever accounts
 * the person synced to the phone (Google and others), with no sign-in of Ira's own.
 */
class CalendarTools(private val context: Context) {
    private val resolver = context.contentResolver

    fun read(args: Args): JsonElement {
        val zone = ZoneId.systemDefault()
        val first = args.string("date", 10)?.let { Args.localDate(it) } ?: LocalDate.now(zone)
        val days = args.int("days", 1, 31, 1)!!
        val query = args.string("query", 80)
        val begin = first.atStartOfDay(zone).toInstant().toEpochMilli()
        val end = first.plusDays(days.toLong()).atStartOfDay(zone).toInstant().toEpochMilli()
        val uri =
            CalendarContract.Instances.CONTENT_URI.buildUpon().also {
                ContentUris.appendId(it, begin)
                ContentUris.appendId(it, end)
            }.build()
        val events = ArrayList<Map<String, Any?>>()
        resolver.query(
            uri,
            arrayOf(
                CalendarContract.Instances.TITLE,
                CalendarContract.Instances.BEGIN,
                CalendarContract.Instances.END,
                CalendarContract.Instances.ALL_DAY,
                CalendarContract.Instances.EVENT_LOCATION,
                CalendarContract.Instances.CALENDAR_DISPLAY_NAME,
            ),
            if (query != null) "${CalendarContract.Instances.TITLE} LIKE ?" else null,
            if (query != null) arrayOf("%${query.replace("%", "")}%") else null,
            "${CalendarContract.Instances.BEGIN} ASC",
        )?.use { c ->
            while (c.moveToNext() && events.size < 50) {
                val allDay = c.getInt(3) == 1
                events +=
                    mapOf(
                        "title" to Results.clip(c.getString(0), 200),
                        "start" to if (allDay) allDayDate(c.getLong(1)) else CallTools.local(c.getLong(1)),
                        "end" to if (allDay) null else CallTools.local(c.getLong(2)),
                        "all_day" to allDay,
                        "location" to Results.clip(c.getString(4)?.ifBlank { null }, 200),
                        "calendar" to c.getString(5),
                    )
            }
        }
        val summary =
            if (events.isEmpty()) {
                "Nothing in the calendar."
            } else {
                events.take(6).joinToString("; ") { "${it["start"]} ${it["title"]}" }
            }
        return Results.of("events" to events, "summary" to summary)
    }

    fun add(args: Args): JsonElement {
        val title = args.string("title", 120, required = true)!!
        val startText = args.string("start", 16, required = true)!!
        val allDay = args.bool("all_day") == true || startText.length == 10
        val location = args.string("location", 120)
        val calendarName = args.string("calendar", 80)
        val zone = ZoneId.systemDefault()
        val values = ContentValues()
        val shown: String
        if (allDay) {
            val day = Args.localDate(startText.take(10), "start")
            // All-day events are stored in UTC, from midnight to midnight.
            values.put(CalendarContract.Events.DTSTART, day.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli())
            values.put(CalendarContract.Events.DTEND, day.plusDays(1).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli())
            values.put(CalendarContract.Events.EVENT_TIMEZONE, "UTC")
            values.put(CalendarContract.Events.ALL_DAY, 1)
            shown = day.toString()
        } else {
            val start = Args.localDateTime(startText, "start")
            val endText = args.string("end", 16)
            val end: LocalDateTime =
                if (endText != null) {
                    Args.localDateTime(endText, "end")
                } else {
                    start.plusMinutes((args.int("duration_minutes", 5, 1440, 60)!!).toLong())
                }
            if (!end.isAfter(start)) throw ToolFailure("the end must be after the start")
            values.put(CalendarContract.Events.DTSTART, start.atZone(zone).toInstant().toEpochMilli())
            values.put(CalendarContract.Events.DTEND, end.atZone(zone).toInstant().toEpochMilli())
            values.put(CalendarContract.Events.EVENT_TIMEZONE, zone.id)
            shown = CallTools.local(start.atZone(zone).toInstant().toEpochMilli())
        }
        val (calendarId, calendar) = pickCalendar(calendarName)
        values.put(CalendarContract.Events.CALENDAR_ID, calendarId)
        values.put(CalendarContract.Events.TITLE, title)
        if (location != null) values.put(CalendarContract.Events.EVENT_LOCATION, location)
        val uri = resolver.insert(CalendarContract.Events.CONTENT_URI, values) ?: throw ToolFailure("the calendar did not take the event")
        return Results.of(
            "event_id" to ContentUris.parseId(uri),
            "calendar" to calendar,
            "summary" to "Added '$title' on $shown to $calendar.",
        )
    }

    private fun allDayDate(utcMillis: Long): String =
        java.time.Instant.ofEpochMilli(utcMillis).atZone(ZoneOffset.UTC).toLocalDate().toString()

    /** The named calendar, else the primary one the person can write to. */
    private fun pickCalendar(name: String?): Pair<Long, String> {
        val writable = "${CalendarContract.Calendars.CALENDAR_ACCESS_LEVEL} >= ${CalendarContract.Calendars.CAL_ACCESS_CONTRIBUTOR}"
        resolver.query(
            CalendarContract.Calendars.CONTENT_URI,
            arrayOf(
                CalendarContract.Calendars._ID,
                CalendarContract.Calendars.CALENDAR_DISPLAY_NAME,
                CalendarContract.Calendars.IS_PRIMARY,
                CalendarContract.Calendars.VISIBLE,
            ),
            writable,
            null,
            null,
        )?.use { c ->
            val found = ArrayList<Triple<Long, String, Boolean>>()
            while (c.moveToNext()) {
                if (c.getInt(3) == 0) continue
                found += Triple(c.getLong(0), c.getString(1).orEmpty(), c.getInt(2) == 1)
            }
            if (found.isEmpty()) throw ToolFailure("there is no calendar on the phone that Ira can add to")
            val pick =
                if (name != null) {
                    found.firstOrNull { it.second.equals(name, ignoreCase = true) }
                        ?: found.firstOrNull { it.second.contains(name, ignoreCase = true) }
                        ?: throw ToolFailure("no calendar is called '$name'; there are: ${found.joinToString(", ") { it.second }}")
                } else {
                    found.firstOrNull { it.third } ?: found.first()
                }
            return pick.first to pick.second
        }
        throw ToolFailure("the phone's calendars could not be read")
    }
}
