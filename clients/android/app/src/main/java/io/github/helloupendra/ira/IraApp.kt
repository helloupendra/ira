package io.github.helloupendra.ira

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.os.Handler
import android.os.Looper
import androidx.core.app.NotificationCompat
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import io.github.helloupendra.ira.core.DeviceFrame
import io.github.helloupendra.ira.core.Paired
import io.github.helloupendra.ira.store.SecretStore
import io.github.helloupendra.ira.store.Settings
import io.github.helloupendra.ira.device.DeviceLink
import io.github.helloupendra.ira.device.LinkState
import io.github.helloupendra.ira.service.ConversationService
import io.github.helloupendra.ira.tools.PhoneState
import io.github.helloupendra.ira.tools.PhoneTools
import io.github.helloupendra.ira.ui.MainActivity
import io.github.helloupendra.ira.voice.LiveSession
import kotlinx.coroutines.Job
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/**
 * The app's few long-lived pieces: settings, the token store, the phone's tools, the
 * device link and the current call. The device link runs while an Ira screen is open or a
 * call is on, and stops a little after both end.
 */
class IraApp : Application() {
    lateinit var settings: Settings
        private set
    lateinit var secrets: SecretStore
        private set
    lateinit var tools: PhoneTools
        private set

    private val main = Handler(Looper.getMainLooper())
    private var link: DeviceLink? = null
    private val holds = HashSet<String>()
    private val linkState = MutableStateFlow<LinkState>(LinkState.Off)
    val deviceStatus: StateFlow<LinkState> = linkState

    private val skills = MutableStateFlow<Set<String>>(emptySet())
    val skillsOn: StateFlow<Set<String>> = skills

    private val call = MutableStateFlow<LiveSession?>(null)
    val session: StateFlow<LiveSession?> = call

    /** Why the last call ended, when it was not the person's own doing; shown on the talk screen. */
    private val ended = MutableStateFlow<String?>(null)
    val lastEnded: StateFlow<String?> = ended

    private val stopLink = Runnable { link?.stop() }
    private val scope = MainScope()
    private var mirror: Job? = null

    override fun onCreate() {
        super.onCreate()
        settings = Settings(this)
        secrets = SecretStore(this)
        tools = PhoneTools(this)
        skills.value = settings.skillsOn
        ProcessLifecycleOwner.get().lifecycle.addObserver(
            object : DefaultLifecycleObserver {
                override fun onStart(owner: LifecycleOwner) = hold("screen")

                override fun onStop(owner: LifecycleOwner) = release("screen")
            },
        )
    }

    val paired: Boolean
        get() = settings.paired && secrets.token() != null

    fun savePairing(paired: Paired) {
        secrets.saveToken(paired.token)
        settings.savePairing(paired)
        skills.value = paired.skills.toSet()
        rebuildLink()
    }

    /** Remove this phone: the server revokes the token, and the phone forgets it. */
    fun unpair(done: () -> Unit) {
        endCall()
        val current = link ?: buildLink()
        link = null
        val finish = {
            secrets.clear()
            settings.forgetPairing()
            skills.value = emptySet()
            linkState.value = LinkState.Off
            done()
        }
        if (current != null) current.unpair(finish) else finish()
    }

    // The call.

    /** A call with Ira: [listen] turns the microphone on (a voice call), else typing only. */
    fun startCall(listen: Boolean): LiveSession? {
        call.value?.let {
            if (listen) it.startListening()
            return it
        }
        val server = settings.server ?: return null
        val session =
            LiveSession(
                context = this,
                server = server,
                token = { secrets.token() },
                conversationId = settings.conversationId,
                listen = listen,
                onConversation = { settings.conversationId = it },
                onEnded = { reason ->
                    ended.value = reason
                    PhoneState.callOn = false
                    call.value = null
                    release("call")
                    stopService(Intent(this, ConversationService::class.java))
                },
            )
        ended.value = null
        call.value = session
        PhoneState.callOn = true
        hold("call")
        session.start()
        return session
    }

    fun endCall() {
        call.value?.end()
    }

    // The device link.

    fun hold(reason: String) {
        main.removeCallbacks(stopLink)
        holds += reason
        if (!paired) return
        (link ?: buildLink())?.start()
    }

    fun release(reason: String) {
        holds -= reason
        if (holds.isEmpty()) {
            main.removeCallbacks(stopLink)
            main.postDelayed(stopLink, LINGER_MS)
        }
    }

    private fun rebuildLink() {
        link?.release()
        link = null
        if (holds.isNotEmpty()) buildLink()?.start()
    }

    private fun buildLink(): DeviceLink? {
        val server = settings.server ?: return null
        val created =
            DeviceLink(
                server = server,
                path = settings.websocketPath,
                token = { secrets.token() },
                label = settings.label,
                runner = tools,
                onSkills = { on ->
                    settings.skillsOn = on.toSet()
                    skills.value = on.toSet()
                },
                onEvent = ::showEvent,
            )
        link = created
        mirror?.cancel()
        mirror = scope.launch { created.status.collect { linkState.value = it } }
        return created
    }

    private fun showEvent(event: DeviceFrame.Event) {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(EVENTS, "Ira's news", NotificationManager.IMPORTANCE_DEFAULT))
        val open = PendingIntent.getActivity(this, 1, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val notification =
            NotificationCompat.Builder(this, EVENTS)
                .setSmallIcon(R.drawable.ic_ira)
                .setContentTitle(event.title.ifBlank { settings.assistant })
                .setContentText(event.text)
                .setStyle(NotificationCompat.BigTextStyle().bigText(event.text))
                .setContentIntent(open)
                .setAutoCancel(true)
                .build()
        if (PhoneState.has(this, android.Manifest.permission.POST_NOTIFICATIONS)) {
            nm.notify((System.currentTimeMillis() % 100_000).toInt() + 100, notification)
        }
    }

    private companion object {
        const val LINGER_MS = 30_000L
        const val EVENTS = "ira_events"
    }
}
