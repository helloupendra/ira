package io.github.helloupendra.ira.ui

import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import io.github.helloupendra.ira.BuildConfig
import io.github.helloupendra.ira.IraApp
import io.github.helloupendra.ira.core.TalkKey
import io.github.helloupendra.ira.tools.PhoneState

class MainActivity : ComponentActivity() {
    /** When Ira's assistant gesture last asked for a call (a clock that only goes up): the talk
     * screen starts one for each request, once. */
    private val talkRequest = mutableLongStateOf(0L)

    /** Bumped when a Drop notification opens Ira: the Drop screen shows. */
    private val dropRequests = mutableIntStateOf(0)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // What Ira reads out here (messages, calls, notifications) stays out of screenshots,
        // screen recordings and the app switcher. Debug builds allow them, for store images.
        if (!BuildConfig.DEBUG) window.setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE)
        enableEdgeToEdge()
        // A screen made again (turned, or the system's) has had its intent already.
        if (savedInstanceState == null) handle(intent)
        val app = application as IraApp
        setContent { IraTheme(app, this) { IraScreens(app, talkRequest.longValue, dropRequests.intValue) } }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    override fun onResume() {
        super.onResume()
        PhoneState.visible = true
        current = java.lang.ref.WeakReference(this)
    }

    override fun onPause() {
        PhoneState.visible = false
        super.onPause()
    }

    private fun handle(intent: Intent?) {
        // Only Ira's own assistant session starts the microphone. Another app sending ASSIST, or
        // TALK without the key, opens Ira, where a tap starts a call.
        if (intent?.action == ACTION_TALK && TalkKey.matches(intent.getStringExtra(TalkKey.EXTRA))) {
            talkRequest.longValue = SystemClock.elapsedRealtimeNanos()
        }
        if (intent?.action == ACTION_DROP) dropRequests.intValue++
    }

    companion object {
        const val ACTION_TALK = "io.github.helloupendra.ira.TALK"
        const val ACTION_DROP = "io.github.helloupendra.ira.DROP"

        private var current = java.lang.ref.WeakReference<MainActivity>(null)

        /**
         * Ira steps aside so the app under it is in front again (the screen tools never use
         * Ira's own window). The live call goes on in its service. Call on the main thread.
         */
        fun stepAside(): Boolean = current.get()?.moveTaskToBack(true) ?: false
    }
}
