package io.github.helloupendra.ira.ui

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.mutableIntStateOf
import io.github.helloupendra.ira.IraApp
import io.github.helloupendra.ira.tools.PhoneState

class MainActivity : ComponentActivity() {
    /** Bumped when the assistant gesture opens Ira: the talk screen starts a call. */
    private val talkRequests = mutableIntStateOf(0)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        handle(intent)
        val app = application as IraApp
        setContent { IraTheme { IraScreens(app, talkRequests.intValue) } }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    override fun onResume() {
        super.onResume()
        PhoneState.visible = true
    }

    override fun onPause() {
        PhoneState.visible = false
        super.onPause()
    }

    private fun handle(intent: Intent?) {
        if (intent?.action == ACTION_TALK || intent?.action == Intent.ACTION_ASSIST) talkRequests.intValue++
    }

    companion object {
        const val ACTION_TALK = "io.github.helloupendra.ira.TALK"
    }
}
