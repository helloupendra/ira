package io.github.helloupendra.ira.tools

import android.app.Notification
import android.app.RemoteInput
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.Parcelable
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import androidx.core.os.BundleCompat
import io.github.helloupendra.ira.core.Args
import io.github.helloupendra.ira.core.ToolFailure
import java.lang.ref.WeakReference
import kotlinx.serialization.json.JsonElement

/**
 * Notification access, which the person switches on in Android's settings. Ira reads the
 * notifications showing at the moment it is asked; nothing is kept, copied or logged.
 * This is how Ira sees WhatsApp, Telegram and other messages, through the phone's own
 * notifications, and answers one through the notification's own reply button.
 */
class IraNotificationListener : NotificationListenerService() {
    override fun onListenerConnected() {
        current = WeakReference(this)
    }

    override fun onListenerDisconnected() {
        current = WeakReference(null)
    }

    companion object {
        @Volatile
        private var current: WeakReference<IraNotificationListener> = WeakReference(null)

        fun active(): Array<StatusBarNotification> {
            val listener = current.get() ?: throw ToolFailure("notification access is off, or Android has not connected it yet")
            return try {
                listener.activeNotifications ?: emptyArray()
            } catch (_: SecurityException) {
                throw ToolFailure("notification access is off")
            }
        }
    }
}

class NotificationTools(private val context: Context) {
    fun read(args: Args): JsonElement {
        val app = args.string("app", 60)
        val limit = args.int("limit", 1, 30, 10)!!
        val items = ArrayList<Map<String, Any?>>()
        val list = IraNotificationListener.active().sortedByDescending { it.postTime }
        for (sbn in list) {
            if (items.size >= limit) break
            if (sbn.packageName == context.packageName) continue
            val n = sbn.notification
            if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) continue
            val label = appLabel(sbn.packageName)
            if (app != null && !label.contains(app, ignoreCase = true) && !sbn.packageName.contains(app, ignoreCase = true)) continue
            val extras = n.extras
            val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()
            val text = (extras.getCharSequence(Notification.EXTRA_BIG_TEXT) ?: extras.getCharSequence(Notification.EXTRA_TEXT))?.toString()
            val messages = messagesOf(extras)
            if (title.isNullOrBlank() && text.isNullOrBlank() && messages.isEmpty()) continue
            items +=
                mapOf(
                    "key" to sbn.key,
                    "app" to label,
                    "title" to Results.clip(title, 200),
                    "text" to Results.clip(text, 1_000),
                    "messages" to messages.ifEmpty { null },
                    "at" to CallTools.local(sbn.postTime),
                    "can_reply" to (replyAction(n) != null),
                )
        }
        val summary =
            if (items.isEmpty()) {
                "No notifications" + (app?.let { " from $it" } ?: "") + "."
            } else {
                items.take(5).joinToString("; ") { "${it["app"]}: ${it["title"] ?: ""} ${Results.clip(it["text"] as String?, 100) ?: ""}".trim() }
            }
        return Results.of("notifications" to items, "summary" to summary)
    }

    fun reply(args: Args): JsonElement {
        val key = args.string("key", 300, required = true)!!
        val text = args.string("text", 1_000, required = true)!!
        val to = args.string("to", 80)
        val sbn = IraNotificationListener.active().firstOrNull { it.key == key }
            ?: throw ToolFailure("that notification is gone; read the notifications again")
        val action = replyAction(sbn.notification) ?: throw ToolFailure("that notification cannot be answered from outside its app")
        val inputs = action.remoteInputs.filter { it.allowFreeFormInput }.toTypedArray()
        val intent = Intent()
        val results = Bundle()
        for (input in inputs) results.putCharSequence(input.resultKey, text)
        RemoteInput.addResultsToIntent(inputs, intent, results)
        RemoteInput.setResultsSource(intent, RemoteInput.SOURCE_FREE_FORM_INPUT)
        try {
            action.actionIntent.send(context, 0, intent)
        } catch (_: Exception) {
            throw ToolFailure("the app did not take the reply")
        }
        val label = appLabel(sbn.packageName)
        return Results.of("app" to label, "to" to to, "summary" to "Replied${to?.let { " to $it" } ?: ""} on $label.")
    }

    private fun replyAction(n: Notification): Notification.Action? =
        n.actions?.firstOrNull { action -> action.remoteInputs?.any { it.allowFreeFormInput } == true }

    private fun messagesOf(extras: Bundle): List<Map<String, String?>> {
        @Suppress("DEPRECATION")
        val raw: Array<Parcelable> = extras.getParcelableArray(Notification.EXTRA_MESSAGES) ?: return emptyList()
        return raw.takeLast(5).mapNotNull { item ->
            val bundle = item as? Bundle ?: return@mapNotNull null
            val text = bundle.getCharSequence("text")?.toString() ?: return@mapNotNull null
            val sender =
                bundle.getCharSequence("sender")?.toString()
                    ?: BundleCompat.getParcelable(bundle, "sender_person", android.app.Person::class.java)?.name?.toString()
            mapOf("from" to sender, "text" to Results.clip(text, 500))
        }
    }

    private fun appLabel(packageName: String): String =
        try {
            val info = context.packageManager.getApplicationInfo(packageName, 0)
            context.packageManager.getApplicationLabel(info).toString()
        } catch (_: Exception) {
            packageName
        }
}
