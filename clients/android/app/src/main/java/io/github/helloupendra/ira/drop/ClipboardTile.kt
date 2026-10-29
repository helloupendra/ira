package io.github.helloupendra.ira.drop

import android.annotation.SuppressLint
import android.app.PendingIntent
import android.content.ClipboardManager
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import android.widget.Toast
import androidx.activity.ComponentActivity
import io.github.helloupendra.ira.IraApp

/**
 * A quick-settings tile, "Send clipboard": what you copied goes to your Drop, and so to all
 * your devices. The tile opens a moment of Ira's own screen, because Android lets an app
 * read the clipboard only while it is in front.
 */
class ClipboardTile : TileService() {
    override fun onStartListening() {
        val tile = qsTile ?: return
        tile.state = if ((application as IraApp).paired) Tile.STATE_INACTIVE else Tile.STATE_UNAVAILABLE
        tile.updateTile()
    }

    @SuppressLint("StartActivityAndCollapseDeprecated")
    override fun onClick() {
        val open = {
            val intent = Intent(this, ClipboardActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (Build.VERSION.SDK_INT >= 34) {
                startActivityAndCollapse(PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE))
            } else {
                @Suppress("DEPRECATION")
                startActivityAndCollapse(intent)
            }
        }
        if (isLocked) unlockAndRun { open() } else open()
    }
}

/** Reads the clipboard once it has the focus, sends it to Drop, says so, and goes. */
class ClipboardActivity : ComponentActivity() {
    private var sent = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        sent = savedInstanceState?.getBoolean(SENT) == true
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putBoolean(SENT, sent)
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!hasFocus || sent) return
        sent = true
        val app = application as IraApp
        val clip = getSystemService(ClipboardManager::class.java)?.primaryClip?.takeIf { it.itemCount > 0 }?.getItemAt(0)
        val uri = clip?.uri
        val text = clip?.coerceToText(this)?.toString()?.trim().orEmpty()
        val done = { problem: String? ->
            Toast.makeText(app, problem ?: "Sent to your Drop.", Toast.LENGTH_SHORT).show()
            finish()
        }
        when {
            !app.paired -> done("Pair this phone with your Ira first.")
            uri != null && uri.scheme == "content" -> app.drop.sendFiles(listOf(uri), null, done)
            text.isNotEmpty() -> app.drop.sendText(text, done)
            else -> done("The clipboard is empty.")
        }
    }

    private companion object {
        const val SENT = "sent"
    }
}
