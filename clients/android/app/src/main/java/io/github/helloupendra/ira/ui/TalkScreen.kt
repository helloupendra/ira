package io.github.helloupendra.ira.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.github.helloupendra.ira.IraApp
import io.github.helloupendra.ira.R
import io.github.helloupendra.ira.device.LinkState
import io.github.helloupendra.ira.service.ConversationService
import io.github.helloupendra.ira.voice.CallStatus
import io.github.helloupendra.ira.voice.CallUi
import kotlinx.coroutines.flow.MutableStateFlow

@Composable
fun TalkScreen(app: IraApp, talkRequests: Int, onSkills: () -> Unit, onSettings: () -> Unit) {
    val context = LocalContext.current
    val session by app.session.collectAsState()
    val idle = remember { MutableStateFlow(CallUi(status = CallStatus.Off, assistant = app.settings.assistant)) }
    val live by (session?.ui ?: idle).collectAsState()
    val endedWhy by app.lastEnded.collectAsState()
    val ui = if (session == null) live.copy(notice = endedWhy) else live
    val link by app.deviceStatus.collectAsState()
    var disclose by remember { mutableStateOf(false) }
    var typed by remember { mutableStateOf("") }
    val server = app.settings.server.orEmpty().removePrefix("https://").removePrefix("http://")

    val micPermission =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) ConversationService.start(context)
        }

    fun talk() {
        when {
            !app.settings.micDisclosureAccepted -> disclose = true
            context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED ->
                micPermission.launch(Manifest.permission.RECORD_AUDIO)
            else -> ConversationService.start(context)
        }
    }

    // The assistant gesture opened Ira: start listening at once.
    LaunchedEffect(talkRequests) { if (talkRequests > 0 && session?.ui?.value?.listening != true) talk() }

    val callOn = ui.status != CallStatus.Off && ui.status != CallStatus.Ended
    Column(Modifier.fillMaxSize().imePadding()) {
        TopRow(ui.assistant) {
            TextButton(onClick = onSkills) { Text("Skills") }
            TextButton(onClick = onSettings) { Text("Settings") }
        }
        StatusLine(ui, link)
        Transcript(ui, Modifier.weight(1f))
        ui.action?.let { card ->
            ActionCardView(
                card = card,
                onYes = { session?.answer(true) },
                onNo = { session?.answer(false) },
                onOpenIra = { open(context, app.settings.server.orEmpty()) },
                onDismiss = { session?.dismissAction() },
            )
        }
        ui.notice?.let {
            Text(
                it,
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp),
            )
        }
        TalkControl(
            ui = ui,
            onTap = {
                when {
                    !callOn || !ui.listening -> talk()
                    ui.status == CallStatus.Speaking -> session?.stopIra()
                    else -> app.endCall()
                }
            },
        )
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedTextField(
                value = typed,
                onValueChange = { typed = it },
                placeholder = { Text("Type to ${ui.assistant}") },
                maxLines = 3,
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.size(8.dp))
            Button(
                enabled = typed.isNotBlank(),
                onClick = {
                    val text = typed
                    typed = ""
                    (session ?: app.startCall(listen = false))?.type(text)
                },
            ) { Text("Send") }
        }
    }

    if (disclose) {
        AlertDialog(
            onDismissRequest = { disclose = false },
            title = { Text(Disclosures.MIC_TITLE) },
            text = { Text(Disclosures.mic(server)) },
            confirmButton = {
                TextButton(onClick = {
                    disclose = false
                    app.settings.micDisclosureAccepted = true
                    talk()
                }) { Text("Agree") }
            },
            dismissButton = { TextButton(onClick = { disclose = false }) { Text("Not now") } },
        )
    }
}

@Composable
private fun StatusLine(ui: CallUi, link: LinkState) {
    val text =
        when (ui.status) {
            CallStatus.Off -> "Tap the microphone to talk, or type."
            CallStatus.Connecting -> "Connecting..."
            CallStatus.Listening -> if (ui.listening) "Listening" else "Connected. Type, or tap the microphone."
            CallStatus.Hearing -> "Hearing you"
            CallStatus.Thinking -> "Thinking"
            CallStatus.Speaking -> "Speaking. Talk to interrupt."
            CallStatus.Reconnecting -> "Reconnecting..."
            CallStatus.Ended -> "Call ended."
        }
    val tools = if (link is LinkState.Connected) "Phone tools: on" else "Phone tools: off"
    Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.primary, modifier = Modifier.weight(1f))
        Text(tools, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun Transcript(ui: CallUi, modifier: Modifier) {
    val list = rememberLazyListState()
    val count = ui.lines.size + if (ui.caption.isNotBlank()) 1 else 0
    LaunchedEffect(count, ui.lines.lastOrNull()?.text?.length) { if (count > 0) list.animateScrollToItem(count - 1) }
    LazyColumn(
        state = list,
        modifier = modifier.fillMaxWidth().padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item { Spacer(Modifier.height(8.dp)) }
        items(ui.lines) { line -> Bubble(line) }
        if (ui.caption.isNotBlank()) {
            item {
                Text(
                    ui.caption,
                    fontStyle = FontStyle.Italic,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.fillMaxWidth().padding(8.dp),
                )
            }
        }
    }
}

@Composable
private fun Bubble(line: CallUi.Line) {
    val mine = !line.fromIra
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start) {
        Box(
            Modifier
                .widthIn(max = 320.dp)
                .clip(RoundedCornerShape(16.dp))
                .background(if (mine) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant)
                .padding(horizontal = 14.dp, vertical = 10.dp),
        ) {
            Text(
                if (line.stopped) line.text + " (stopped)" else line.text,
                style = MaterialTheme.typography.bodyLarge,
                color = if (mine) MaterialTheme.colorScheme.onPrimaryContainer else MaterialTheme.colorScheme.onSurface,
            )
        }
    }
}

@Composable
private fun ActionCardView(
    card: io.github.helloupendra.ira.core.ActionCard,
    onYes: () -> Unit,
    onNo: () -> Unit,
    onOpenIra: () -> Unit,
    onDismiss: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(if (card.needsPin) "Needs your PIN" else "Needs your yes", fontWeight = FontWeight.SemiBold)
            Text(card.summary, style = MaterialTheme.typography.bodyLarge)
            if (card.needsPin) {
                Text(
                    "Confirm it with your PIN in the Ira app. A PIN is never spoken, and never typed here.",
                    style = MaterialTheme.typography.bodySmall,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = onOpenIra) { Text("Open Ira") }
                    TextButton(onClick = onDismiss) { Text("Close") }
                }
            } else {
                Text("Say \"haan\" or \"yes\", or tap.", style = MaterialTheme.typography.bodySmall)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = onYes, enabled = card.canApprove) { Text("Yes") }
                    OutlinedButton(onClick = onNo) { Text("No") }
                }
            }
        }
    }
}

@Composable
private fun TalkControl(ui: CallUi, onTap: () -> Unit) {
    val active = ui.listening && ui.status != CallStatus.Ended
    val pulse by animateFloatAsState(if (active) 1f + minOf(ui.level * 6f, 0.25f) else 1f, label = "level")
    val label =
        when {
            !active -> "Talk"
            ui.status == CallStatus.Speaking -> "Stop"
            else -> "End"
        }
    Column(
        Modifier.fillMaxWidth().padding(vertical = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(contentAlignment = Alignment.Center, modifier = Modifier.size(132.dp)) {
            if (active) {
                Box(
                    Modifier.size(132.dp).scale(pulse).clip(CircleShape).background(MaterialTheme.colorScheme.primary.copy(alpha = 0.18f)),
                )
            }
            Box(
                contentAlignment = Alignment.Center,
                modifier =
                    Modifier
                        .size(96.dp)
                        .clip(CircleShape)
                        .background(MaterialTheme.colorScheme.primary)
                        .clickable(onClick = onTap)
                        .semantics { contentDescription = "$label: talk to Ira" },
            ) {
                Icon(painterResource(R.drawable.ic_mic), contentDescription = null, tint = MaterialTheme.colorScheme.onPrimary, modifier = Modifier.size(40.dp))
            }
        }
        Text(label, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
