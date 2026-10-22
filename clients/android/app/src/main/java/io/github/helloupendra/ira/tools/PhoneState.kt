package io.github.helloupendra.ira.tools

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.role.RoleManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.provider.Settings
import androidx.core.app.NotificationCompat
import io.github.helloupendra.ira.R
import io.github.helloupendra.ira.core.Permissions
import io.github.helloupendra.ira.core.SpecialAccess
import java.util.concurrent.atomic.AtomicInteger

/** What the phone allows Ira right now, read fresh each time a tool runs. */
object PhoneState {
    /** An Ira screen (the app, or the assistant panel) is showing. */
    @Volatile
    var visible: Boolean = false

    /** A live call with Ira is on in this app. */
    @Volatile
    var callOn: Boolean = false

    fun isAssistant(context: Context): Boolean {
        val roles = context.getSystemService(RoleManager::class.java) ?: return false
        return roles.isRoleAvailable(RoleManager.ROLE_ASSISTANT) && roles.isRoleHeld(RoleManager.ROLE_ASSISTANT)
    }

    fun granted(context: Context, permissions: Collection<String>): Set<String> =
        permissions.filter { has(context, it) }.toSet()

    fun has(context: Context, permission: String): Boolean {
        // Notifications need no runtime permission before Android 13.
        if (permission == Permissions.POST_NOTIFICATIONS && Build.VERSION.SDK_INT < 33) return true
        return context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
    }

    fun special(context: Context): Set<SpecialAccess> {
        val out = HashSet<SpecialAccess>()
        if (notificationAccess(context)) out += SpecialAccess.NOTIFICATION_LISTENER
        if (accessibilityOn(context)) out += SpecialAccess.ACCESSIBILITY
        val alarms = context.getSystemService(android.app.AlarmManager::class.java)
        if (Build.VERSION.SDK_INT < 31 || alarms?.canScheduleExactAlarms() == true) out += SpecialAccess.EXACT_ALARMS
        val nm = context.getSystemService(NotificationManager::class.java)
        if (nm?.isNotificationPolicyAccessGranted == true) out += SpecialAccess.DO_NOT_DISTURB
        return out
    }

    fun notificationAccess(context: Context): Boolean {
        val enabled = Settings.Secure.getString(context.contentResolver, "enabled_notification_listeners") ?: return false
        val mine = ComponentName(context, IraNotificationListener::class.java).flattenToString()
        return enabled.split(':').any { it == mine }
    }

    fun accessibilityOn(context: Context): Boolean {
        val service = ScreenAccess.serviceName(context) ?: return false
        val enabled = Settings.Secure.getString(context.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: return false
        return enabled.split(':').any { it.equals(service, ignoreCase = true) }
    }

    val RECORD_AUDIO = Manifest.permission.RECORD_AUDIO
}

/**
 * Starts another app's screen for a tool (the dialer, the clock, maps).
 *
 * Android lets an app start a screen from the background only in some cases: when one of
 * its own screens is showing, or when it is the phone's digital assistant. Otherwise the
 * phone shows a notification that does it on a tap, and the tool says so.
 */
object Launcher {
    private const val CHANNEL = "ira_actions"
    private val ids = AtomicInteger(5000)

    /** True when the screen was started; false when a notification asks for a tap. */
    fun start(context: Context, intent: Intent, tapToWhat: String): Boolean {
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (PhoneState.visible || PhoneState.isAssistant(context)) {
            try {
                context.startActivity(intent)
                return true
            } catch (_: Exception) {
                // fall through to the notification
            }
        }
        notifyTap(context, intent, tapToWhat)
        return false
    }

    fun notifyTap(context: Context, intent: Intent, tapToWhat: String) {
        val nm = context.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Ira's actions", NotificationManager.IMPORTANCE_HIGH))
        val id = ids.incrementAndGet()
        val pending = PendingIntent.getActivity(context, id, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val notification =
            NotificationCompat.Builder(context, CHANNEL)
                .setSmallIcon(R.drawable.ic_ira)
                .setContentTitle("Tap to $tapToWhat")
                .setContentIntent(pending)
                .setAutoCancel(true)
                .setCategory(NotificationCompat.CATEGORY_REMINDER)
                .build()
        if (PhoneState.has(context, Permissions.POST_NOTIFICATIONS)) nm.notify(id, notification)
    }
}
