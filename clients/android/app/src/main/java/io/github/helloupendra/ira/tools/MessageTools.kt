package io.github.helloupendra.ira.tools

import android.content.Context
import android.os.Build
import android.provider.Telephony
import android.telephony.SmsManager
import io.github.helloupendra.ira.core.Args
import io.github.helloupendra.ira.core.Permissions
import io.github.helloupendra.ira.core.ToolFailure
import kotlinx.serialization.json.JsonElement

/** SMS: reading the inbox and sending a message. */
class MessageTools(private val context: Context) {
    fun smsRead(args: Args): JsonElement {
        val from = args.string("from", 80)
        val contains = args.string("contains", 80)
        val limit = args.int("limit", 1, 20, 5)!!
        val sinceHours = args.int("since_hours", 1, 24 * 30)
        val where = ArrayList<String>()
        val values = ArrayList<String>()
        if (contains != null) {
            where += "${Telephony.Sms.BODY} LIKE ?"
            values += "%${contains.replace("%", "").replace("_", "")}%"
        }
        if (sinceHours != null) {
            where += "${Telephony.Sms.DATE} >= ?"
            values += (System.currentTimeMillis() - sinceHours * 3_600_000L).toString()
        }
        val names = ContactNames(context)
        val fromKey = from?.let { if (it.any(Char::isDigit)) Args.numberKey(it) else null }
        val messages = ArrayList<Map<String, Any?>>()
        context.contentResolver.query(
            Telephony.Sms.Inbox.CONTENT_URI,
            arrayOf(Telephony.Sms.ADDRESS, Telephony.Sms.BODY, Telephony.Sms.DATE, Telephony.Sms.READ),
            where.joinToString(" AND ").ifEmpty { null },
            values.toTypedArray().ifEmpty { null },
            "${Telephony.Sms.DATE} DESC",
        )?.use { c ->
            var scanned = 0
            while (c.moveToNext() && messages.size < limit && scanned < 500) {
                scanned++
                val address = c.getString(0).orEmpty()
                val name = names.forNumber(address)
                if (from != null) {
                    val matches =
                        if (fromKey != null) {
                            Args.numberKey(address) == fromKey
                        } else {
                            name?.contains(from, ignoreCase = true) == true || address.contains(from, ignoreCase = true)
                        }
                    if (!matches) continue
                }
                messages +=
                    mapOf(
                        "from" to (name ?: address),
                        "number" to address,
                        "at" to CallTools.local(c.getLong(2)),
                        "unread" to (c.getInt(3) == 0),
                        "text" to Results.clip(c.getString(1), 1_000),
                    )
            }
        }
        val summary =
            if (messages.isEmpty()) {
                "No messages match."
            } else {
                messages.take(3).joinToString("; ") { "${it["from"]} at ${it["at"]}: ${Results.clip(it["text"] as String?, 120)}" }
            }
        return Results.of("messages" to messages, "summary" to summary)
    }

    fun smsSend(args: Args): JsonElement {
        val number = Args.phoneNumber(args.string("number", 24, required = true)!!)
        val name = args.string("name", 80)
        val text = args.string("text", 1_000, required = true)!!
        if (!PhoneState.has(context, Permissions.SEND_SMS)) throw ToolFailure("the phone has not allowed Ira to send SMS")
        val sms =
            if (Build.VERSION.SDK_INT >= 31) {
                context.getSystemService(SmsManager::class.java)
            } else {
                @Suppress("DEPRECATION")
                SmsManager.getDefault()
            } ?: throw ToolFailure("this phone cannot send SMS")
        val parts = sms.divideMessage(text)
        if (parts.size > 1) sms.sendMultipartTextMessage(number, null, parts, null, null) else sms.sendTextMessage(number, null, text, null, null)
        val who = name ?: number
        return Results.of("number" to number, "name" to name, "parts" to parts.size, "summary" to "Sent the SMS to $who.")
    }
}
