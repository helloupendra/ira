package io.github.helloupendra.ira.tools

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.provider.Telephony
import android.telephony.SmsManager
import androidx.core.content.ContextCompat
import io.github.helloupendra.ira.core.Args
import io.github.helloupendra.ira.core.Permissions
import io.github.helloupendra.ira.core.SmsCount
import io.github.helloupendra.ira.core.SmsOutcome
import io.github.helloupendra.ira.core.ToolFailure
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlinx.serialization.json.JsonElement

/** SMS: reading the inbox and sending a message. */
private const val MAX_SCANNED = 500

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
        var found = 0
        var unread = 0
        var scanned = 0
        context.contentResolver.query(
            Telephony.Sms.Inbox.CONTENT_URI,
            arrayOf(Telephony.Sms.ADDRESS, Telephony.Sms.BODY, Telephony.Sms.DATE, Telephony.Sms.READ),
            where.joinToString(" AND ").ifEmpty { null },
            values.toTypedArray().ifEmpty { null },
            "${Telephony.Sms.DATE} DESC",
        )?.use { c ->
            while (c.moveToNext() && scanned < MAX_SCANNED) {
                scanned++
                val address = c.getString(0).orEmpty()
                val name = if (from != null || messages.size < limit) names.forNumber(address) else null
                if (from != null) {
                    val matches =
                        if (fromKey != null) {
                            Args.numberKey(address) == fromKey
                        } else {
                            name?.contains(from, ignoreCase = true) == true || address.contains(from, ignoreCase = true)
                        }
                    if (!matches) continue
                }
                found++
                val isUnread = c.getInt(3) == 0
                if (isUnread) unread++
                if (messages.size < limit) {
                    messages +=
                        mapOf(
                            "from" to (name ?: address),
                            "number" to address,
                            "at" to CallTools.local(c.getLong(2)),
                            "unread" to isUnread,
                            "text" to Results.clip(c.getString(1), 1_000),
                        )
                }
            }
        }
        val summary =
            if (messages.isEmpty()) {
                "No messages match."
            } else {
                SmsCount.line(found, unread, messages.size, scanned >= MAX_SCANNED) + " " +
                    messages.take(3).joinToString("; ") { "${it["from"]} at ${it["at"]}: ${Results.clip(it["text"] as String?, 120)}" }
            }
        return Results.of("messages" to messages, "found" to found, "unread" to unread, "summary" to summary)
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
        val codes = sendAndWait(sms, number, text, parts)
        val who = name ?: number
        SmsOutcome.failure(codes)?.let { throw ToolFailure("the SMS to $who did not go: $it") }
        val sent = SmsOutcome.sent(codes)
        // Not confirmed in time: the phone has it and may still send it, so it is no failure.
        val summary = if (sent) "Sent the SMS to $who." else "Gave the SMS to $who to the phone; it has not yet said it went."
        return Results.of("number" to number, "name" to name, "parts" to parts.size, "sent" to sent, "summary" to summary)
    }

    /** Send, then wait a little for the phone to say each part went (or why it did not). */
    private fun sendAndWait(sms: SmsManager, number: String, text: String, parts: ArrayList<String>): List<Int?> {
        val action = "${context.packageName}.SMS_SENT.${System.nanoTime()}"
        val codes = LinkedBlockingQueue<Int>()
        val receiver =
            object : BroadcastReceiver() {
                override fun onReceive(c: Context, intent: Intent) {
                    codes.offer(resultCode)
                }
            }
        ContextCompat.registerReceiver(context, receiver, IntentFilter(action), ContextCompat.RECEIVER_NOT_EXPORTED)
        try {
            val sent =
                ArrayList(
                    parts.indices.map {
                        PendingIntent.getBroadcast(
                            context,
                            it,
                            Intent(action).setPackage(context.packageName),
                            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_ONE_SHOT,
                        )
                    },
                )
            if (parts.size > 1) sms.sendMultipartTextMessage(number, null, parts, sent, null) else sms.sendTextMessage(number, null, text, sent[0], null)
            val until = System.nanoTime() + SEND_WAIT_MS * 1_000_000L
            return parts.indices.map { codes.poll(maxOf(0L, (until - System.nanoTime()) / 1_000_000L), TimeUnit.MILLISECONDS) }
        } finally {
            runCatching { context.unregisterReceiver(receiver) }
        }
    }

    private companion object {
        const val SEND_WAIT_MS = 20_000L
    }
}
