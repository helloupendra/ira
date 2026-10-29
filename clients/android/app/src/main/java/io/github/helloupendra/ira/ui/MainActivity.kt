package io.github.helloupendra.ira.ui

import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.mutableIntStateOf
import io.github.helloupendra.ira.BuildConfig
import io.github.helloupendra.ira.IraApp
import io.github.helloupendra.ira.tools.PhoneState

class MainActivity : ComponentActivity() {
    /** Bumped when the assistant gesture opens Ira: the talk screen starts a call. */
    private val talkRequests = mutableIntStateOf(0)

    /** Bumped when a Drop notification opens Ira: the Drop screen shows. */
    private val dropRequests = mutableIntStateOf(0)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // What Ira reads out here (messages, calls, notifications) stays out of screenshots,
        // screen recordings and the app switcher. Debug builds allow them, for store images.
        if (!BuildConfig.DEBUG) window.setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE)
        enableEdgeToEdge()
        handle(intent)
        val app = application as IraApp
        setContent { IraTheme { IraScreens(app, talkRequests.intValue, dropRequests.intValue) } }
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
        if (intent?.action == ACTION_TALK || intent?.action == Intent.ACTION_ASSIST) talkRequests.intValue++
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
