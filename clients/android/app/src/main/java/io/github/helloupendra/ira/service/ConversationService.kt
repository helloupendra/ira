package io.github.helloupendra.ira.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import io.github.helloupendra.ira.IraApp
import io.github.helloupendra.ira.R
import io.github.helloupendra.ira.tools.PhoneState
import io.github.helloupendra.ira.ui.MainActivity

/**
 * A foreground service of type `microphone`, on only while a call with Ira is on.
 *
 * The person starts it (the talk button, or the assistant gesture), its notification shows
 * the whole time the microphone may listen, and its End button, the app's End button, or
 * two quiet minutes stop it. It never starts on its own, at boot or otherwise.
 */
class ConversationService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val app = application as IraApp
        if (intent?.action == ACTION_END) {
            app.endCall()
            stopSelf()
            return START_NOT_STICKY
        }
        if (!PhoneState.has(this, PhoneState.RECORD_AUDIO)) {
            stopSelf()
            return START_NOT_STICKY
        }
        // The microphone type is Android 11's; Android 10 has no such limit on a foreground service.
        val type = if (Build.VERSION.SDK_INT >= 30) ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE else 0
        ServiceCompat.startForeground(this, ID, notification(), type)
        if (app.startLive() == null) stopSelf()
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        (application as IraApp).endCall()
        super.onDestroy()
    }

    private fun notification(): android.app.Notification {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Talking with Ira", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val end =
            PendingIntent.getService(
                this,
                1,
                Intent(this, ConversationService::class.java).setAction(ACTION_END),
                PendingIntent.FLAG_IMMUTABLE,
            )
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_ira)
            .setContentTitle("Talking with ${(application as IraApp).settings.assistant}")
            .setContentText("The microphone is on for this call. Nothing is recorded.")
            .setContentIntent(open)
            .addAction(0, "End", end)
            .setOngoing(true)
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .build()
    }

    companion object {
        private const val ID = 7
        private const val CHANNEL = "ira_call"
        private const val ACTION_END = "io.github.helloupendra.ira.END_CALL"

        /** Start a call: only from a screen the person is using (the app, or the assistant panel). */
        fun start(context: Context) {
            ContextCompat.startForegroundService(context, Intent(context, ConversationService::class.java))
        }

        fun end(context: Context) {
            context.startService(Intent(context, ConversationService::class.java).setAction(ACTION_END))
        }
    }
}
