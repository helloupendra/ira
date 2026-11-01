package io.github.helloupendra.ira.ui

import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
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
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.helloupendra.ira.IraApp
import io.github.helloupendra.ira.R
import io.github.helloupendra.ira.core.Drop
import io.github.helloupendra.ira.drop.DropBox

/**
 * Drop: send text, a link or files to all your devices, and see what arrived from them,
 * newest first under Today, Yesterday and older dates. Text and links have Copy first; files
 * are saved to Downloads/Ira.
 */
@Composable
fun DropScreen(app: IraApp, onBack: () -> Unit) {
    val context = LocalContext.current
    val colors = Presence.colors
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
    Column(Modifier.fillMaxSize().background(colors.bg)) {
        ScreenHeader("Drop", onBack, subtitle = "Shared by your devices for 30 days")
        LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
            // One read of the list: it can change before this screen recomposes.
            val shown = items
            val days = shown.map { Drop.day(it) }
            item {
                Column(Modifier.padding(top = 8.dp, bottom = 4.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Column(
                        Modifier.fillMaxWidth().presenceCard(colors, radius = 18.dp, fill = colors.raised).padding(14.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Box(Modifier.fillMaxWidth().heightIn(min = 52.dp)) {
                            if (text.isEmpty()) Text("Text or a link", fontSize = 16.sp, color = colors.faint)
                            BasicTextField(
                                value = text,
                                onValueChange = { text = it },
                                textStyle = TextStyle(fontSize = 16.sp, lineHeight = 22.sp, color = colors.ink),
                                cursorBrush = SolidColor(colors.green),
                                modifier = Modifier.fillMaxWidth().semantics { contentDescription = "Text or a link" },
                            )
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            PillButton("Send", filled = true, enabled = text.isNotBlank() && !busy, onClick = {
                                busy = true
                                drop.sendText(text) { problem ->
                                    busy = false
                                    message = problem
                                    if (problem == null) text = ""
                                }
                            })
                            PillButton("Choose files", { pick.launch("*/*") })
                            PillButton("Paste", { clipboardText(context)?.let { text = it } })
                        }
                    }
                    Text(
                        "It shows up on all your devices at once, and stays 30 days. Or share to Ira from any app.",
                        fontSize = 12.sp,
                        color = colors.faint,
                    )
                    message?.let { Text(it, fontSize = 13.sp, color = colors.down) }
                }
            }
            items(uploads, key = { "up${it.key}" }) { up ->
                Column(Modifier.padding(top = 10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(up.name, maxLines = 1, overflow = TextOverflow.Ellipsis, fontSize = 12.sp, color = colors.muted)
                    if (up.error == null) {
                        LinearProgressIndicator(
                            progress = { up.progress },
                            modifier = Modifier.fillMaxWidth(),
                            color = colors.green,
                            trackColor = colors.line,
                            gapSize = 0.dp,
                            drawStopIndicator = {},
                        )
                    } else {
                        Text(up.error, fontSize = 12.sp, color = colors.down)
                    }
                }
            }
            if (shown.isEmpty()) {
                item {
                    Text(
                        "Nothing here yet. What you send from any of your devices shows up here.",
                        Modifier.padding(top = 24.dp),
                        fontSize = 15.sp,
                        color = colors.muted,
                    )
                }
            }
            shown.forEachIndexed { index, item ->
                val first = index == 0 || days[index] != days[index - 1]
                if (first) {
                    item(key = "day${item.id}") {
                        Text(days[index].uppercase(), Modifier.padding(start = 4.dp, top = 24.dp, bottom = 8.dp), style = Presence.label, color = colors.muted)
                    }
                }
                val last = index == shown.lastIndex || days[index] != days[index + 1]
                item(key = item.id) {
                    Column(Modifier.groupRow(colors, first, last)) {
                        if (!first) Hairline()
                        DropRow(app, item, onDelete = { deleting = item })
                    }
                }
            }
            if (hasMore) {
                item {
                    Box(Modifier.padding(top = 12.dp)) { PillButton("Show older", { drop.loadOlder { message = it } }) }
                }
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
                }) { Text("Delete", color = colors.down) }
            },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text("Keep", color = colors.ink) } },
        )
    }
}

/** One item: its kind, what it is, where it came from, and its actions. */
@Composable
private fun DropRow(app: IraApp, item: Drop.Item, onDelete: () -> Unit) {
    val context = LocalContext.current
    val colors = Presence.colors
    var saved by remember(item.id) { mutableStateOf<Uri?>(null) }
    var saving by remember(item.id) { mutableStateOf(false) }
    var problem by remember(item.id) { mutableStateOf<String?>(null) }
    Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 14.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Box(Modifier.size(36.dp).presenceCard(colors, radius = 10.dp), contentAlignment = Alignment.Center) {
            Icon(painterResource(kindIcon(item)), contentDescription = null, tint = colors.green, modifier = Modifier.size(18.dp))
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            if (item.isFile) {
                Text(Drop.title(item), fontSize = 15.sp, fontWeight = FontWeight.Medium, color = colors.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
                item.text?.takeIf { it.isNotBlank() }?.let { Text(it, fontSize = 14.sp, color = colors.ink, maxLines = 6, overflow = TextOverflow.Ellipsis) }
            } else {
                SelectionContainer {
                    Text(item.text.orEmpty(), fontSize = 15.sp, lineHeight = 22.sp, color = colors.ink, maxLines = 12, overflow = TextOverflow.Ellipsis)
                }
            }
            Text(Drop.detail(item), fontSize = 12.sp, color = colors.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            problem?.let { Text(it, fontSize = 12.sp, color = colors.down) }
            Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                if (item.isFile) {
                    val file = saved
                    if (file == null) {
                        PillButton(if (saving) "Saving..." else "Save", enabled = !saving, compact = true, onClick = {
                            saving = true
                            problem = null
                            app.drop.save(item) { uri, error ->
                                saving = false
                                saved = uri
                                problem = error
                            }
                        })
                    } else {
                        PillButton("Open", { openFile(context, file, item.mime) }, compact = true)
                    }
                } else {
                    PillButton("Copy", { DropBox.copy(context, item.text.orEmpty()) }, compact = true)
                    item.link?.let { link -> PillButton("Open", { open(context, link) }, compact = true) }
                }
                PillButton("Delete", onDelete, compact = true)
            }
            if (saved != null) Text("Saved in Downloads/Ira.", fontSize = 12.sp, color = colors.muted)
        }
    }
}

private fun kindIcon(item: Drop.Item): Int =
    when (item.kind) {
        "file" -> R.drawable.ic_file
        "link" -> R.drawable.ic_link
        else -> R.drawable.ic_text
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
