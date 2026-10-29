package io.github.helloupendra.ira.drop

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.IntentCompat
import io.github.helloupendra.ira.IraApp
import io.github.helloupendra.ira.core.Drop
import io.github.helloupendra.ira.ui.IraTheme
import kotlinx.coroutines.delay

/**
 * Share → Ira from any app: what was shared, shown first, and sent to the person's Drop only
 * on Send to Drop. Any app can start this screen, so nothing goes without that tap.
 */
class ShareActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val app = application as IraApp
        val shared = shared(intent)
        setContent { IraTheme { ShareSheet(app, shared) { finish() } } }
    }

    /** What came in: the words, and the files (each readable while this screen is open). */
    data class Shared(val text: String, val files: List<Uri>)

    private fun shared(intent: Intent?): Shared {
        if (intent == null) return Shared("", emptyList())
        val text = Drop.sharedText(intent.getStringExtra(Intent.EXTRA_TEXT), intent.getStringExtra(Intent.EXTRA_SUBJECT))
        val files =
            when (intent.action) {
                Intent.ACTION_SEND -> listOfNotNull(IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java))
                Intent.ACTION_SEND_MULTIPLE -> IntentCompat.getParcelableArrayListExtra(intent, Intent.EXTRA_STREAM, Uri::class.java).orEmpty()
                else -> emptyList()
            }
        // Only content from other apps: never a file of this app's own.
        return Shared(text, files.filter { it.scheme == "content" && it.authority?.startsWith(packageName) != true }.take(MAX_FILES))
    }

    private companion object {
        const val MAX_FILES = 20
    }
}

@Composable
private fun ShareSheet(app: IraApp, shared: ShareActivity.Shared, close: () -> Unit) {
    val uploads by app.drop.uploads.collectAsState()
    var state by remember { mutableStateOf("ask") }
    var problem by remember { mutableStateOf<String?>(null) }
    val described = remember(shared) { shared.files.map { app.drop.describe(it) } }
    LaunchedEffect(state) {
        if (state == "sent") {
            delay(1200)
            close()
        }
    }
    Box(
        Modifier.fillMaxSize().background(Color(0x66000000)).clickable(
            interactionSource = remember { MutableInteractionSource() },
            indication = null,
        ) { if (state != "sending") close() },
        contentAlignment = Alignment.BottomCenter,
    ) {
        Card(
            Modifier.fillMaxWidth().padding(12.dp).navigationBarsPadding().clickable(
                interactionSource = remember { MutableInteractionSource() },
                indication = null,
            ) {},
        ) {
            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Send to your Drop?", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                when {
                    !app.paired -> Text("Pair this phone with your Ira first: open Ira, then Settings.")
                    shared.text.isEmpty() && shared.files.isEmpty() -> Text("Nothing came with this share.")
                    else -> {
                        Column(Modifier.heightIn(max = 260.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            if (shared.text.isNotEmpty()) Text(shared.text, maxLines = 8, overflow = TextOverflow.Ellipsis)
                            for ((name, length) in described) {
                                Text(if (length >= 0) "$name (${Drop.size(length)})" else name, style = MaterialTheme.typography.bodyMedium)
                            }
                        }
                        Text(
                            "It goes to all your devices once you send it, and stays 30 days.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                if (state == "sending") {
                    for (up in uploads.filter { it.error == null }) {
                        Text(up.name, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall)
                        LinearProgressIndicator(progress = { up.progress }, modifier = Modifier.fillMaxWidth())
                    }
                }
                if (state == "sent") Text("Sent. It is on your other devices now.", color = MaterialTheme.colorScheme.primary)
                problem?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    val ready = app.paired && (shared.text.isNotEmpty() || shared.files.isNotEmpty())
                    if (ready && state == "ask") {
                        Button(onClick = {
                            state = "sending"
                            problem = null
                            val done = { error: String? ->
                                problem = error
                                state = if (error == null) "sent" else "ask"
                            }
                            if (shared.files.isEmpty()) app.drop.sendText(shared.text, done) else app.drop.sendFiles(shared.files, shared.text.ifEmpty { null }, done)
                        }) { Text("Send to Drop") }
                    }
                    if (state != "sending") TextButton(onClick = close) { Text(if (state == "sent") "Close" else "Cancel") }
                }
            }
        }
    }
}
