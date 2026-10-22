package io.github.helloupendra.ira.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.lifecycle.compose.LifecycleResumeEffect
import io.github.helloupendra.ira.core.Actions
import io.github.helloupendra.ira.core.Checklist
import io.github.helloupendra.ira.core.Permissions
import io.github.helloupendra.ira.net.Net
import io.github.helloupendra.ira.tools.PhoneState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
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
    val scope = rememberCoroutineScope()
    val session by app.session.collectAsState()
    val idle = remember { MutableStateFlow(CallUi(status = CallStatus.Off, assistant = app.settings.assistant)) }
    val live by (session?.ui ?: idle).collectAsState()
    val endedWhy by app.lastEnded.collectAsState()
    val ui = if (session == null) live.copy(notice = endedWhy) else live
    val link by app.deviceStatus.collectAsState()
    var disclose by remember { mutableStateOf<Boolean?>(null) } // null: closed; true: then start a call
    var micRefused by remember { mutableStateOf(false) }
    var notificationsRefused by remember { mutableStateOf(false) }
    var typed by remember { mutableStateOf("") }
    var confirming by remember { mutableStateOf(false) }
    var outcome by remember { mutableStateOf<String?>(null) }
    var refresh by remember { mutableIntStateOf(0) }
    val server = app.settings.server.orEmpty().removePrefix("https://").removePrefix("http://")
    LifecycleResumeEffect(Unit) {
        refresh++
        onPauseOrDispose { }
    }

    var callAfterGrant by remember { mutableStateOf(false) }
    val micPermission =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            refresh++
            micRefused = !granted
            if (granted && callAfterGrant) ConversationService.start(context)
        }
    val notificationPermission =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            refresh++
            notificationsRefused = !granted
        }

    fun hasMic() = context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    /** The microphone, asked for right after Ira's own explanation; [call] starts a call too. */
    fun microphone(call: Boolean) {
        callAfterGrant = call
        when {
            !app.settings.micDisclosureAccepted -> disclose = call
            hasMic() -> if (call) ConversationService.start(context)
            micRefused -> openAppSettings(context)
            else -> micPermission.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    fun talk() = microphone(call = true)

    // The assistant gesture opened Ira: start listening at once.
    LaunchedEffect(talkRequests) { if (talkRequests > 0 && session?.ui?.value?.listening != true) talk() }

    val callOn = ui.status != CallStatus.Off && ui.status != CallStatus.Ended
    val skillsOn by app.skillsOn.collectAsState()
    val facts =
        remember(refresh, skillsOn) {
            val state = app.tools.gateState()
            Checklist.Facts(
                microphone = hasMic(),
                notifications = if (Build.VERSION.SDK_INT >= 33) PhoneState.has(context, Permissions.POST_NOTIFICATIONS) else null,
                assistant = state.assistantRole,
                skillsOnServer = skillsOn,
                skillsWaitingOnPhone = skillsWaitingOnPhone(app, state, skillsOn),
            )
        }
    var checklistHidden by remember { mutableStateOf(app.settings.checklistHidden) }

    Column(Modifier.fillMaxSize().imePadding()) {
        TopRow(ui.assistant) {
            TextButton(onClick = onSkills) { Text("Skills") }
            TextButton(onClick = onSettings) { Text("Settings") }
        }
        StatusLine(ui, link)
        if (!checklistHidden && !Checklist.complete(facts) && !callOn) {
            ChecklistCard(
                steps = Checklist.steps(facts),
                refused = { action ->
                    (action == Checklist.Action.ALLOW_MICROPHONE && micRefused) ||
                        (action == Checklist.Action.ALLOW_NOTIFICATIONS && notificationsRefused)
                },
                onAction = { action ->
                    when (action) {
                        Checklist.Action.ALLOW_MICROPHONE -> microphone(call = false)
                        Checklist.Action.ALLOW_NOTIFICATIONS ->
                            if (notificationsRefused || Build.VERSION.SDK_INT < 33) {
                                openNotificationSettings(context)
                            } else {
                                notificationPermission.launch(Permissions.POST_NOTIFICATIONS)
                            }
                        Checklist.Action.OPEN_ASSISTANT_SETTINGS -> openAssistantSettings(context)
                        Checklist.Action.OPEN_YOUR_IRA -> open(context, app.settings.server.orEmpty())
                        Checklist.Action.OPEN_SKILLS -> onSkills()
                    }
                },
                onHide = {
                    checklistHidden = true
                    app.settings.checklistHidden = true
                },
            )
        }
        Transcript(ui, Modifier.weight(1f))
        ui.action?.let { card ->
            ActionCardView(
                card = card,
                busy = confirming,
                outcome = outcome,
                onYes = { session?.answer(true) },
                onNo = { session?.answer(false) },
                onPin = { pin ->
                    confirming = true
                    outcome = null
                    scope.launch {
                        val result =
                            withContext(Dispatchers.IO) {
                                Actions.confirm(app.settings.server.orEmpty(), app.secrets.token().orEmpty(), card.id, pin, Net.post)
                            }
                        confirming = false
                        outcome = result.message
                        if (result.done) {
                            session?.dismissAction()
                            outcome = null
                            session?.note(result.message)
                        }
                    }
                },
                onDismiss = {
                    outcome = null
                    session?.dismissAction()
                },
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

    disclose?.let { thenCall ->
        AlertDialog(
            onDismissRequest = { disclose = null },
            title = { Text(Disclosures.MIC_TITLE) },
            text = { Text(Disclosures.mic(server)) },
            confirmButton = {
                TextButton(onClick = {
                    disclose = null
                    app.settings.micDisclosureAccepted = true
                    microphone(call = thenCall)
                }) { Text("Agree") }
            },
            dismissButton = { TextButton(onClick = { disclose = null }) { Text("Not now") } },
        )
    }
}

@Composable
private fun ChecklistCard(
    steps: List<Checklist.Step>,
    refused: (Checklist.Action) -> Boolean,
    onAction: (Checklist.Action) -> Unit,
    onHide: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "Get Ira ready: ${steps.count { it.done }} of ${steps.size} done",
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = onHide) { Text("Hide") }
            }
            for (step in steps) {
                Row(verticalAlignment = Alignment.Top) {
                    Text(if (step.done) "✓" else "○", color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(end = 10.dp, top = 2.dp))
                    Column(Modifier.weight(1f)) {
                        Text(step.title, style = MaterialTheme.typography.bodyLarge)
                        if (!step.done) {
                            Text(step.detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            val label = if (refused(step.action)) "Open settings" else step.button
                            TextButton(onClick = { onAction(step.action) }) { Text(label) }
                            if (refused(step.action)) {
                                Text(
                                    "Android remembers your earlier No. In the settings that open, choose Permissions (or Notifications) and allow it for Ira.",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
            }
        }
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
    busy: Boolean,
    outcome: String?,
    onYes: () -> Unit,
    onNo: () -> Unit,
    onPin: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var pin by remember(card.id) { mutableStateOf("") }
    Card(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(if (card.needsPin) "Needs your PIN" else "Needs your yes", fontWeight = FontWeight.SemiBold)
            Text(card.summary, style = MaterialTheme.typography.bodyLarge)
            if (card.needsPin) {
                Text("Type your action PIN to confirm. Never say a PIN aloud.", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(
                    value = pin,
                    onValueChange = { value -> pin = value.filter { it.isDigit() }.take(12) },
                    label = { Text("PIN") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(
                        enabled = !busy && pin.length >= 4,
                        onClick = {
                            val typedPin = pin
                            pin = ""
                            onPin(typedPin)
                        },
                    ) { Text(if (busy) "Checking..." else "Confirm") }
                    TextButton(onClick = onDismiss) { Text("Not now") }
                }
            } else {
                Text("Say \"haan\" or \"yes\", or tap.", style = MaterialTheme.typography.bodySmall)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = onYes, enabled = card.canApprove) { Text("Yes") }
                    OutlinedButton(onClick = onNo) { Text("No") }
                }
            }
            outcome?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium) }
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
