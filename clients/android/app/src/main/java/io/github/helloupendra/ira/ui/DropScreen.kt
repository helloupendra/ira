package io.github.helloupendra.ira.ui

import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.helloupendra.ira.IraApp
import io.github.helloupendra.ira.core.Drop
import io.github.helloupendra.ira.drop.DropBox

/**
 * Drop: send text, a link or files to all your devices, and see what arrived from them,
 * newest first. Text and links have Copy first; files are saved to Downloads/Ira.
 */
@Composable
fun DropScreen(app: IraApp, onBack: () -> Unit) {
    val context = LocalContext.current
    val drop = app.drop
    val items by drop.items.collectAsState()
    val hasMore by drop.hasMore.collectAsState()
    val uploads by drop.uploads.collectAsState()
    var text by rememberSaveable { mutableStateOf("") }
    var message by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf<Drop.Item?>(null) }
    val pick =
        rememberLauncherForActivityResult(ActivityResultContracts.GetMultipleContents()) { uris ->
            if (uris.isNotEmpty()) drop.sendFiles(uris, null) { message = it }
        }
    LaunchedEffect(Unit) { drop.refresh { message = it } }
    DisposableEffect(Unit) {
        drop.visible = true
        onDispose {
            drop.visible = false
            drop.clearFailed()
        }
    }

    Column(Modifier.fillMaxSize()) {
        TopRow("Drop", onBack)
        LazyColumn(
            Modifier.fillMaxSize().padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = text,
                        onValueChange = { text = it },
                        label = { Text("Text or a link") },
                        modifier = Modifier.fillMaxWidth().heightIn(min = 72.dp),
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(enabled = text.isNotBlank() && !busy, onClick = {
                            busy = true
                            drop.sendText(text) { problem ->
                                busy = false
                                message = problem
                                if (problem == null) text = ""
                            }
                        }) { Text("Send") }
                        OutlinedButton(onClick = { pick.launch("*/*") }) { Text("Choose files") }
                        TextButton(onClick = { clipboardText(context)?.let { text = it } }) { Text("Paste") }
                    }
                    Text(
                        "It shows up on all your devices at once, and stays 30 days. Or share to Ira from any app.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                }
            }
            items(uploads, key = { "up${it.key}" }) { up ->
                Column {
                    Text(up.name, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall)
                    if (up.error == null) {
                        LinearProgressIndicator(progress = { up.progress }, modifier = Modifier.fillMaxWidth())
                    } else {
                        Text(up.error, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
            if (items.isEmpty()) {
                item {
                    Text(
                        "Nothing here yet. What you send from any of your devices shows up here.",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            items(items, key = { it.id }) { item -> DropCard(app, item, onDelete = { deleting = item }) }
            if (hasMore) {
                item { TextButton(onClick = { drop.loadOlder { message = it } }) { Text("Show older") } }
            }
            item { Row(Modifier.padding(bottom = 24.dp)) {} }
        }
    }

    deleting?.let { item ->
        AlertDialog(
            onDismissRequest = { deleting = null },
            title = { Text("Delete from all your devices?") },
            text = { Text(Drop.preview(item)) },
            confirmButton = {
                TextButton(onClick = {
                    deleting = null
                    drop.delete(item) { message = it }
                }) { Text("Delete") }
            },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text("Keep") } },
        )
    }
}

@Composable
private fun DropCard(app: IraApp, item: Drop.Item, onDelete: () -> Unit) {
    val context = LocalContext.current
    var saved by remember(item.id) { mutableStateOf<Uri?>(null) }
    var saving by remember(item.id) { mutableStateOf(false) }
    var problem by remember(item.id) { mutableStateOf<String?>(null) }
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            if (item.isFile) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(Drop.safeName(item.name), fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f, fill = false))
                    Text(Drop.size(item.size ?: 0), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                item.text?.takeIf { it.isNotBlank() }?.let { Text(it, maxLines = 6, overflow = TextOverflow.Ellipsis) }
            } else {
                SelectionContainer { Text(item.text.orEmpty(), maxLines = 12, overflow = TextOverflow.Ellipsis) }
            }
            Text("From ${item.fromLabel.ifBlank { "a device" }}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            problem?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (item.isFile) {
                    val file = saved
                    if (file == null) {
                        Button(enabled = !saving, onClick = {
                            saving = true
                            problem = null
                            app.drop.save(item) { uri, error ->
                                saving = false
                                saved = uri
                                problem = error
                            }
                        }) { Text(if (saving) "Saving..." else "Save") }
                    } else {
                        Button(onClick = { openFile(context, file, item.mime) }) { Text("Open") }
                    }
                } else {
                    Button(onClick = { DropBox.copy(context, item.text.orEmpty()) }) { Text("Copy") }
                    item.link?.let { link -> OutlinedButton(onClick = { open(context, link) }) { Text("Open") } }
                }
                TextButton(onClick = onDelete) { Text("Delete") }
            }
            if (saved != null) Text("Saved in Downloads/Ira.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/** The clipboard's text, read while this screen is in front (Android allows it only then). */
private fun clipboardText(context: Context): String? =
    context.getSystemService(ClipboardManager::class.java)?.primaryClip?.takeIf { it.itemCount > 0 }
        ?.getItemAt(0)?.coerceToText(context)?.toString()?.takeIf { it.isNotBlank() }

/** A saved file, in the app the phone opens that kind of file with. */
private fun openFile(context: Context, uri: Uri, mime: String?) {
    try {
        context.startActivity(
            Intent(Intent.ACTION_VIEW).setDataAndType(uri, mime ?: "application/octet-stream")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    } catch (_: Exception) {
    }
}
