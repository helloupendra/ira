package io.github.helloupendra.ira.tools

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.CallLog
import android.provider.ContactsContract
import io.github.helloupendra.ira.core.Args
import io.github.helloupendra.ira.core.Permissions
import io.github.helloupendra.ira.core.ToolFailure
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlinx.serialization.json.JsonElement

/** Calls and contacts: the call log, the contacts, and placing a call. */
class CallTools(private val context: Context) {
    private val resolver = context.contentResolver

    fun callsRecent(args: Args): JsonElement {
        val limit = args.int("limit", 1, 50, 10)!!
        val kind = args.choice("kind", listOf("any", "missed", "incoming", "outgoing"), "any")!!
        val sinceHours = args.int("since_hours", 1, 24 * 30)
        val where = ArrayList<String>()
        val values = ArrayList<String>()
        when (kind) {
            "missed" -> where += "${CallLog.Calls.TYPE} IN (${CallLog.Calls.MISSED_TYPE}, ${CallLog.Calls.REJECTED_TYPE})"
            "incoming" -> where += "${CallLog.Calls.TYPE} = ${CallLog.Calls.INCOMING_TYPE}"
            "outgoing" -> where += "${CallLog.Calls.TYPE} = ${CallLog.Calls.OUTGOING_TYPE}"
        }
        if (sinceHours != null) {
            where += "${CallLog.Calls.DATE} >= ?"
            values += (System.currentTimeMillis() - sinceHours * 3_600_000L).toString()
        }
        val names = ContactNames(context)
        val calls = ArrayList<Map<String, Any?>>()
        resolver.query(
            CallLog.Calls.CONTENT_URI,
            arrayOf(CallLog.Calls.NUMBER, CallLog.Calls.CACHED_NAME, CallLog.Calls.TYPE, CallLog.Calls.DATE, CallLog.Calls.DURATION),
            where.joinToString(" AND ").ifEmpty { null },
            values.toTypedArray().ifEmpty { null },
            "${CallLog.Calls.DATE} DESC",
        )?.use { c ->
            while (c.moveToNext() && calls.size < limit) {
                val number = c.getString(0).orEmpty()
                val name = names.forNumber(number) ?: c.getString(1)?.takeIf { it.isNotBlank() }
                calls +=
                    mapOf(
                        "name" to name,
                        "number" to number.ifEmpty { "private number" },
                        "kind" to kindOf(c.getInt(2)),
                        "at" to local(c.getLong(3)),
                        "seconds" to c.getLong(4),
                    )
            }
        }
        val summary =
            if (calls.isEmpty()) {
                "No calls."
            } else {
                calls.take(5).joinToString("; ") { "${it["kind"]} ${if (it["kind"] == "outgoing") "to" else "from"} ${it["name"] ?: it["number"]} at ${it["at"]}" }
            }
        return Results.of("calls" to calls, "summary" to summary)
    }

    fun contactsLookup(args: Args): JsonElement {
        val query = args.string("query", 100, required = true)!!
        val limit = args.int("limit", 1, 20, 5)!!
        val people = LinkedHashMap<Long, MutableMap<String, Any?>>()
        // The phone's own filter matches a name (any word of it) or a number (any format).
        val uri = Uri.withAppendedPath(ContactsContract.CommonDataKinds.Phone.CONTENT_FILTER_URI, Uri.encode(query))
        resolver.query(
            uri,
            arrayOf(
                ContactsContract.CommonDataKinds.Phone.CONTACT_ID,
                ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                ContactsContract.CommonDataKinds.Phone.NUMBER,
                ContactsContract.CommonDataKinds.Phone.TYPE,
                ContactsContract.CommonDataKinds.Phone.LABEL,
            ),
            null,
            null,
            null,
        )?.use { c ->
            while (c.moveToNext()) {
                val id = c.getLong(0)
                if (id !in people && people.size >= limit) continue
                val person = people.getOrPut(id) { mutableMapOf("name" to c.getString(1), "numbers" to ArrayList<Map<String, String>>()) }
                @Suppress("UNCHECKED_CAST")
                val numbers = person["numbers"] as MutableList<Map<String, String>>
                val number = c.getString(2).orEmpty()
                if (numbers.none { Args.numberKey(it["number"].orEmpty()) == Args.numberKey(number) }) {
                    val label =
                        ContactsContract.CommonDataKinds.Phone.getTypeLabel(context.resources, c.getInt(3), c.getString(4)).toString()
                    numbers += mapOf("number" to number, "label" to label)
                }
            }
        }
        val list = people.values.toList()
        val summary =
            when (list.size) {
                0 -> "Nobody in the contacts matches '$query'."
                1 -> "${list[0]["name"]}: ${numbersOf(list[0])}"
                else -> "${list.size} people match: " + list.joinToString("; ") { "${it["name"]} (${numbersOf(it)})" }
            }
        return Results.of("people" to list, "summary" to summary)
    }

    fun callPlace(args: Args): JsonElement {
        val number = Args.phoneNumber(args.string("number", 24, required = true)!!)
        val name = args.string("name", 80)
        if (!PhoneState.has(context, Permissions.CALL_PHONE)) throw ToolFailure("the phone has not allowed Ira to make calls")
        val intent = Intent(Intent.ACTION_CALL, Uri.fromParts("tel", number, null))
        val who = name ?: number
        val started = Launcher.start(context, intent, "call $who")
        return Results.of(
            "number" to number,
            "name" to name,
            "started" to started,
            "summary" to if (started) "Calling $who." else "The phone shows a notification: tap it to call $who.",
        )
    }

    private fun numbersOf(person: Map<String, Any?>): String {
        @Suppress("UNCHECKED_CAST")
        val numbers = person["numbers"] as List<Map<String, String>>
        return numbers.joinToString(", ") { "${it["number"]} (${it["label"]})" }
    }

    private fun kindOf(type: Int): String =
        when (type) {
            CallLog.Calls.INCOMING_TYPE -> "incoming"
            CallLog.Calls.OUTGOING_TYPE -> "outgoing"
            CallLog.Calls.MISSED_TYPE -> "missed"
            CallLog.Calls.REJECTED_TYPE -> "rejected"
            CallLog.Calls.BLOCKED_TYPE -> "blocked"
            CallLog.Calls.VOICEMAIL_TYPE -> "voicemail"
            else -> "other"
        }

    companion object {
        private val TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")

        fun local(millis: Long): String = TIME.format(Instant.ofEpochMilli(millis).atZone(ZoneId.systemDefault()))
    }
}

/** Names for numbers, from the phone's contacts, when the person allowed contacts. */
class ContactNames(private val context: Context) {
    private val cache = HashMap<String, String?>()
    private val allowed = PhoneState.has(context, Permissions.READ_CONTACTS)

    fun forNumber(number: String): String? {
        if (!allowed || number.isBlank()) return null
        return cache.getOrPut(number) {
            context.contentResolver.query(
                Uri.withAppendedPath(ContactsContract.PhoneLookup.CONTENT_FILTER_URI, Uri.encode(number)),
                arrayOf(ContactsContract.PhoneLookup.DISPLAY_NAME),
                null,
                null,
                null,
            )?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
        }
    }
}
