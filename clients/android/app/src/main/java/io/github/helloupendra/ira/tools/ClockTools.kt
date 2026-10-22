package io.github.helloupendra.ira.tools

import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.AlarmClock
import androidx.core.app.NotificationCompat
import io.github.helloupendra.ira.R
import io.github.helloupendra.ira.core.Args
import io.github.helloupendra.ira.core.Permissions
import io.github.helloupendra.ira.core.ToolFailure
import io.github.helloupendra.ira.core.parseObject
import io.github.helloupendra.ira.core.long
import io.github.helloupendra.ira.core.string
import io.github.helloupendra.ira.core.toJson
import java.time.DayOfWeek
import java.time.LocalDateTime
import java.time.ZoneId
import java.util.Calendar
import kotlinx.serialization.json.JsonElement

/** Alarms and timers in the phone's clock app, and Ira's own reminders. */
class ClockTools(private val context: Context) {
    fun alarm(args: Args): JsonElement {
        val hour = args.requireInt("hour", 0, 23)
        val minute = args.requireInt("minute", 0, 59)
        val label = args.string("label", 60)
        val days = args.list("days").map { Args.dayOfWeek(it) }
        val intent =
            Intent(AlarmClock.ACTION_SET_ALARM)
                .putExtra(AlarmClock.EXTRA_HOUR, hour)
                .putExtra(AlarmClock.EXTRA_MINUTES, minute)
                .putExtra(AlarmClock.EXTRA_SKIP_UI, true)
        if (label != null) intent.putExtra(AlarmClock.EXTRA_MESSAGE, label)
        if (days.isNotEmpty()) intent.putExtra(AlarmClock.EXTRA_DAYS, ArrayList(days.map { calendarDay(it) }))
        val time = "%02d:%02d".format(hour, minute)
        val started = Launcher.start(context, intent, "set the $time alarm")
        return Results.of(
            "time" to time,
            "label" to label,
            "started" to started,
            "summary" to if (started) "Alarm set for $time." else "The phone shows a notification: tap it to set the $time alarm.",
        )
    }

    fun timer(args: Args): JsonElement {
        val seconds = args.requireInt("seconds", 1, 86_400)
        val label = args.string("label", 60)
        val intent =
            Intent(AlarmClock.ACTION_SET_TIMER)
                .putExtra(AlarmClock.EXTRA_LENGTH, seconds)
                .putExtra(AlarmClock.EXTRA_SKIP_UI, true)
        if (label != null) intent.putExtra(AlarmClock.EXTRA_MESSAGE, label)
        val length = if (seconds % 60 == 0) "${seconds / 60} min" else "$seconds s"
        val started = Launcher.start(context, intent, "start the $length timer")
        return Results.of(
            "seconds" to seconds,
            "started" to started,
            "summary" to if (started) "Timer started: $length." else "The phone shows a notification: tap it to start the $length timer.",
        )
    }

    fun reminder(args: Args): JsonElement {
        val text = args.string("text", 200, required = true)!!
        val at = args.string("at", 16)
        val inMinutes = args.int("in_minutes", 1, 525_600)
        val zone = ZoneId.systemDefault()
        val whenLocal =
            when {
                at != null -> Args.localDateTime(at)
                inMinutes != null -> LocalDateTime.now(zone).plusMinutes(inMinutes.toLong())
                else -> throw ToolFailure("say when: 'at' or 'in_minutes'")
            }
        val millis = whenLocal.atZone(zone).toInstant().toEpochMilli()
        if (millis < System.currentTimeMillis() - 60_000) throw ToolFailure("that time has passed")
        if (!PhoneState.has(context, Permissions.POST_NOTIFICATIONS)) throw ToolFailure("the phone has not allowed Ira to show notifications")
        val exact = Reminders.schedule(context, millis, text)
        val shown = CallTools.local(millis)
        return Results.of(
            "at" to shown,
            "exact" to exact,
            "summary" to "Reminder set for $shown" + (if (exact) "." else " (Android may show it a few minutes late)."),
        )
    }

    private fun calendarDay(day: DayOfWeek): Int =
        when (day) {
            DayOfWeek.MONDAY -> Calendar.MONDAY
            DayOfWeek.TUESDAY -> Calendar.TUESDAY
            DayOfWeek.WEDNESDAY -> Calendar.WEDNESDAY
            DayOfWeek.THURSDAY -> Calendar.THURSDAY
            DayOfWeek.FRIDAY -> Calendar.FRIDAY
            DayOfWeek.SATURDAY -> Calendar.SATURDAY
            DayOfWeek.SUNDAY -> Calendar.SUNDAY
        }
}

/**
 * Ira's reminders on the phone: kept in the app's private storage until they go off (so a
 * restart does not lose them), shown as a notification, then forgotten.
 */
object Reminders {
    private const val PREFS = "ira_reminders"
    private const val CHANNEL = "ira_reminders"
    const val EXTRA_ID = "id"

    /** Returns whether the alarm is exact (the person allowed alarms and reminders). */
    fun schedule(context: Context, millis: Long, text: String): Boolean {
        val id = (System.currentTimeMillis() % Int.MAX_VALUE).toInt()
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        prefs.edit().putString(id.toString(), toJson(mapOf("at" to millis, "text" to text)).toString()).apply()
        return arm(context, id, millis)
    }

    fun arm(context: Context, id: Int, millis: Long): Boolean {
        val alarms = context.getSystemService(AlarmManager::class.java)
        val pending =
            PendingIntent.getBroadcast(
                context,
                id,
                Intent(context, ReminderReceiver::class.java).putExtra(EXTRA_ID, id),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
        val exact = Build.VERSION.SDK_INT < 31 || alarms.canScheduleExactAlarms()
        if (exact) {
            alarms.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, millis, pending)
        } else {
            alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, millis, pending)
        }
        return exact
    }

    /** After a restart: arm the ones still to come, show the ones missed. */
    fun rearm(context: Context) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        for ((key, value) in prefs.all) {
            val data = parseObject(value as? String ?: continue) ?: continue
            val at = data.long("at") ?: continue
            val id = key.toIntOrNull() ?: continue
            if (at <= System.currentTimeMillis()) fire(context, id) else arm(context, id, at)
        }
    }

    fun fire(context: Context, id: Int) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val data = prefs.getString(id.toString(), null)?.let { parseObject(it) } ?: return
        prefs.edit().remove(id.toString()).apply()
        val text = data.string("text") ?: return
        val nm = context.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Reminders", NotificationManager.IMPORTANCE_HIGH))
        val open = context.packageManager.getLaunchIntentForPackage(context.packageName)
        val tap = open?.let { PendingIntent.getActivity(context, id, it, PendingIntent.FLAG_IMMUTABLE) }
        val notification =
            NotificationCompat.Builder(context, CHANNEL)
                .setSmallIcon(R.drawable.ic_ira)
                .setContentTitle("Reminder")
                .setContentText(text)
                .setStyle(NotificationCompat.BigTextStyle().bigText(text))
                .setCategory(NotificationCompat.CATEGORY_REMINDER)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setContentIntent(tap)
                .setAutoCancel(true)
                .build()
        if (PhoneState.has(context, Permissions.POST_NOTIFICATIONS)) nm.notify(id, notification)
    }
}

class ReminderReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        Reminders.fire(context, intent.getIntExtra(Reminders.EXTRA_ID, -1))
    }
}

/** Reminders survive a restart of the phone. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) Reminders.rearm(context)
    }
}
