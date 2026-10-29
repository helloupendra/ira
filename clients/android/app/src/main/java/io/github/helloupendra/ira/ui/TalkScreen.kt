package io.github.helloupendra.ira.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.lifecycle.compose.LifecycleResumeEffect
import io.github.helloupendra.ira.approvals.DeviceKey
import io.github.helloupendra.ira.approvals.Fingerprint
import io.github.helloupendra.ira.core.Actions
import io.github.helloupendra.ira.core.Approvals
import io.github.helloupendra.ira.core.Checklist
import io.github.helloupendra.ira.core.Permissions
import io.github.helloupendra.ira.net.Net
import io.github.helloupendra.ira.tools.PhoneState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.selection.selectable
import androidx.compose.material3.RadioButton
import androidx.compose.ui.semantics.Role
import io.github.helloupendra.ira.core.Reports
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
import io.github.helloupendra.ira.voice.CallStatus
import io.github.helloupendra.ira.voice.CallUi
import io.github.helloupendra.ira.voice.PhoneSession
import io.github.helloupendra.ira.voice.TalkMode
import io.github.helloupendra.ira.voice.Transcript
import kotlinx.coroutines.flow.MutableStateFlow

@Composable
fun TalkScreen(app: IraApp, talkRequests: Int, onSkills: () -> Unit, onSettings: () -> Unit, onDrop: () -> Unit = {}) {
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
    var sending by remember { mutableStateOf(false) }
    var sendError by remember { mutableStateOf<String?>(null) }
    val lines by app.transcript.lines.collectAsState()
    var confirming by remember { mutableStateOf(false) }
    // What happened to the last action, shown once its card is gone: (title, short result).
    var result by remember { mutableStateOf<Pair<String, String?>?>(null) }
    var refresh by remember { mutableIntStateOf(0) }
    var reporting by remember { mutableStateOf<Transcript.Line?>(null) }
    val server = app.settings.server.orEmpty().removePrefix("https://").removePrefix("http://")
    LifecycleResumeEffect(Unit) {
        refresh++
        app.refreshApprovals()
        onPauseOrDispose { }
    }

    var callAfterGrant by remember { mutableStateOf(false) }
    val micPermission =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            refresh++
            micRefused = !granted
            if (granted && callAfterGrant) app.startVoice(context)
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
            hasMic() -> if (call) app.startVoice(context)
            micRefused -> openAppSettings(context)
            else -> micPermission.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    fun talk() = microphone(call = true)

    // The assistant gesture opened Ira: start listening at once.
    LaunchedEffect(talkRequests) { if (talkRequests > 0 && session?.ui?.value?.listening != true) talk() }

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
            TextButton(onClick = onDrop) { Text("Drop") }
            TextButton(onClick = onSkills) { Text("Skills") }
            TextButton(onClick = onSettings) { Text("Settings") }
        }
        StatusLine(ui, link)
        if (!checklistHidden && !Checklist.complete(facts) && !ui.listening) {
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
        // This phone's approval window, counted down here and stoppable.
        val approvals by app.approvals.collectAsState()
        var now by remember { mutableLongStateOf(System.currentTimeMillis() / 1000) }
        val window = approvals?.forDevice(app.settings.deviceId, now.toDouble())
        LaunchedEffect(window?.id, window?.expiresAt) {
            while (window != null && window.expiresAt > now) {
                delay(15_000)
                now = System.currentTimeMillis() / 1000
            }
        }
        if (Approvals.WINDOW && window != null) ApprovalBanner(app, window.id, window.secondsLeft(now.toDouble()))
        Conversation(ui, lines, Modifier.weight(1f), onReport = { reporting = it })
        val card = ui.action
        // Only the newest pending action is shown: a new one replaces the card and any result.
        LaunchedEffect(card?.id) {
            if (card == null) return@LaunchedEffect
            result = null
            val seconds = card.expiresIn ?: return@LaunchedEffect
            delay(seconds * 1000L)
            if (session?.ui?.value?.action?.id == card.id) {
                session?.dismissAction()
                result = "That request expired" to "Ask Ira again."
            }
        }
        if (card != null) {
            // The PIN's outcome belongs to this card only.
            var outcome by remember(card.id) { mutableStateOf<String?>(null) }
            // An answer that ended the action: never a stale card; what happened shows instead.
            val settle = { confirmed: Actions.Outcome ->
                if (confirmed.done) {
                    if (session?.ui?.value?.action?.id == card.id) session?.dismissAction()
                    if (Approvals.covered(card.tool)) app.refreshApprovals()
                    val title = if (confirmed.status == "executed") "Done: ${confirmed.message}" else confirmed.message
                    result = title to confirmed.detail
                    session?.note(listOfNotNull(title, confirmed.detail).joinToString(" "))
                    // Ira carries on after the action: her answer as her next message, unless
                    // the open live call already spoke it as its own turn.
                    val reply = confirmed.reply
                    if (reply != null && !confirmed.continuedInCall) {
                        app.transcript.add(Transcript.Line("reply:${card.id}", true, reply, messageId = confirmed.replyMessageId))
                    }
                } else {
                    outcome = confirmed.message
                }
            }
            val answer = { yes: Boolean ->
                confirming = true
                outcome = null
                scope.launch {
                    val answered =
                        withContext(Dispatchers.IO) {
                            Actions.answer(app.settings.server.orEmpty(), app.secrets.token().orEmpty(), card.id, yes, Net.post)
                        }
                    confirming = false
                    settle(answered)
                }
            }
            val activity = context as? android.app.Activity
            val fingerprint =
                if (Approvals.FINGERPRINT && card.needsPin && activity != null && app.settings.approvalsEnrolled && DeviceKey.exists()) {
                    {
                        // The server signs the same bytes: the action, the summary shown, its expiry.
                        val expiresAt = card.expiresAt ?: (System.currentTimeMillis() / 1000 + (card.expiresIn ?: 120))
                        val payload = Approvals.payload(card.id, card.summary, expiresAt)
                        Fingerprint.approve(activity, card.summary, payload) { signature, problem ->
                            if (signature == null) {
                                outcome = problem
                            } else {
                                confirming = true
                                scope.launch {
                                    val confirmed = withContext(Dispatchers.IO) { app.confirmWithKey(card.id, signature) }
                                    confirming = false
                                    if (confirmed.done) {
                                        if (session?.ui?.value?.action?.id == card.id) session?.dismissAction()
                                        result = "Done: ${confirmed.message}" to confirmed.detail
                                        app.refreshApprovals()
                                    } else {
                                        outcome = confirmed.message
                                    }
                                }
                            }
                        }
                    }
                } else {
                    null
                }
            ActionCardView(
                card = card,
                busy = confirming,
                outcome = outcome,
                onFingerprint = fingerprint,
                onYes = { answer(true) },
                onNo = { answer(false) },
                onPin = { pin ->
                    confirming = true
                    outcome = null
                    scope.launch {
                        val confirmed =
                            withContext(Dispatchers.IO) {
                                Actions.confirm(app.settings.server.orEmpty(), app.secrets.token().orEmpty(), card.id, pin, Net.post)
                            }
                        confirming = false
                        settle(confirmed)
                    }
                },
                onDismiss = { session?.dismissAction() },
            )
        } else {
            result?.let { (title, detail) -> ResultCard(title, detail) { result = null } }
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
                val current = session
                when {
                    current == null || !ui.listening -> talk()
                    ui.status == CallStatus.Speaking -> current.stopIra()
                    current is PhoneSession -> current.stopListening()
                    else -> app.endCall()
                }
            },
        )
        fun send() {
            val text = typed.trim()
            if (text.isEmpty() || sending) return
            sending = true
            sendError = null
            app.send(text) { error ->
                sending = false
                if (error == null) {
                    // Ira has it: clear the field, unless the person typed on meanwhile.
                    if (typed.trim() == text) typed = ""
                } else {
                    sendError = error
                }
            }
        }
        sendError?.let { error ->
            Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(error, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                TextButton(onClick = { send() }, enabled = !sending) { Text("Retry") }
            }
        }
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedTextField(
                value = typed,
                onValueChange = {
                    typed = it
                    sendError = null
                },
                placeholder = { Text("Type to ${ui.assistant}") },
                maxLines = 3,
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.size(8.dp))
            Button(enabled = typed.isNotBlank() && !sending, onClick = { send() }) { Text(if (sending) "Sending" else "Send") }
        }
    }

    reporting?.let { line ->
        ReportDialog(
            line = line,
            onSend = { reason, note, done ->
                scope.launch {
                    val result =
                        withContext(Dispatchers.IO) {
                            Reports.send(app.settings.server.orEmpty(), app.secrets.token().orEmpty(), line.messageId ?: 0, reason, note, Net.post)
                        }
                    done(result)
                }
            },
            onClose = { reporting = null },
        )
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
            CallStatus.Listening -> if (ui.listening) "Listening" else "Type, or tap the microphone."
            CallStatus.Hearing -> "Hearing you"
            CallStatus.Thinking -> "Thinking"
            CallStatus.Speaking -> "Speaking. Talk to interrupt."
            CallStatus.Reconnecting -> "Reconnecting..."
            CallStatus.Ended -> "Call ended."
        }
    val tools = if (link is LinkState.Connected) "Phone tools: on" else "Phone tools: off"
    // Which way Ira hears: the server (a live call) or the phone's own recognition.
    val mode =
        when {
            ui.mode == TalkMode.LIVE && ui.status != CallStatus.Ended -> "Live call · "
            ui.mode == TalkMode.PHONE -> "Talk (phone recognition) · "
            else -> ""
        }
    Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(mode + text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.primary, modifier = Modifier.weight(1f))
        Text(tools, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun Conversation(ui: CallUi, lines: List<Transcript.Line>, modifier: Modifier, onReport: (Transcript.Line) -> Unit) {
    val list = rememberLazyListState()
    val count = lines.size + 1 + if (ui.caption.isNotBlank()) 1 else 0
    LaunchedEffect(count, lines.lastOrNull()?.text?.length) { list.animateScrollToItem(count - 1) }
    LazyColumn(
        state = list,
        modifier = modifier.fillMaxWidth().padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item { Spacer(Modifier.height(8.dp)) }
        items(lines, key = { it.key }) { line -> Bubble(line, onReport) }
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
private fun Bubble(line: Transcript.Line, onReport: (Transcript.Line) -> Unit) {
    val mine = !line.fromIra
    val reportable = line.fromIra && line.messageId != null
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start,
        verticalAlignment = Alignment.Top,
    ) {
        Box(
            Modifier
                .widthIn(max = 300.dp)
                .clip(RoundedCornerShape(16.dp))
                .background(if (mine) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant)
                .then(
                    if (reportable) {
                        Modifier.combinedClickable(onClick = {}, onLongClick = { onReport(line) }, onLongClickLabel = "Report this answer")
                    } else {
                        Modifier
                    },
                )
                .padding(horizontal = 14.dp, vertical = 10.dp),
        ) {
            Text(
                if (line.stopped) line.text + " (stopped)" else line.text,
                style = MaterialTheme.typography.bodyLarge,
                color = if (mine) MaterialTheme.colorScheme.onPrimaryContainer else MaterialTheme.colorScheme.onSurface,
            )
        }
        if (reportable) {
            Text(
                "⋮",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier =
                    Modifier
                        .clip(CircleShape)
                        .clickable(onClickLabel = "Report this answer") { onReport(line) }
                        .padding(horizontal = 10.dp, vertical = 6.dp)
                        .semantics { contentDescription = "Report this answer" },
            )
        }
    }
}

/** Report one of Ira's answers: a reason, an optional note, then send. */
@Composable
private fun ReportDialog(line: Transcript.Line, onSend: (reason: String, note: String, done: (Reports.Result) -> Unit) -> Unit, onClose: () -> Unit) {
    var reason by remember(line.messageId) { mutableStateOf<String?>(null) }
    var note by remember(line.messageId) { mutableStateOf("") }
    var busy by remember(line.messageId) { mutableStateOf(false) }
    var result by remember(line.messageId) { mutableStateOf<Reports.Result?>(null) }
    AlertDialog(
        onDismissRequest = { if (!busy) onClose() },
        title = { Text("Report this answer") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    "\"${line.text.take(140)}${if (line.text.length > 140) "…" else ""}\"",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                val done = result
                if (done?.ok == true) {
                    Text(done.message, color = MaterialTheme.colorScheme.primary)
                } else {
                    Text("What is wrong with it?", fontWeight = FontWeight.SemiBold)
                    for ((value, label) in Reports.REASONS) {
                        Row(
                            Modifier.fillMaxWidth().selectable(selected = reason == value, onClick = { reason = value }, role = Role.RadioButton),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            RadioButton(selected = reason == value, onClick = null)
                            Text(label, modifier = Modifier.padding(start = 8.dp))
                        }
                    }
                    OutlinedTextField(
                        value = note,
                        onValueChange = { note = it.take(Reports.MAX_NOTE) },
                        label = { Text("A note (optional)") },
                        maxLines = 4,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Text(
                        "The report goes to your Ira's owner with this answer. Nothing else is sent.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    done?.let { Text(it.message, color = MaterialTheme.colorScheme.error) }
                }
            }
        },
        confirmButton = {
            if (result?.ok == true) {
                TextButton(onClick = onClose) { Text("Close") }
            } else {
                TextButton(
                    enabled = reason != null && !busy,
                    onClick = {
                        busy = true
                        onSend(reason!!, note) {
                            busy = false
                            result = it
                        }
                    },
                ) { Text(if (busy) "Sending..." else "Send") }
            }
        },
        dismissButton = { if (result?.ok != true) TextButton(onClick = onClose, enabled = !busy) { Text("Cancel") } },
    )
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
    onFingerprint: (() -> Unit)? = null,
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
                onFingerprint?.let { approve ->
                    Button(onClick = approve, enabled = !busy) { Text("Approve with fingerprint") }
                    Text("Or type your PIN:", style = MaterialTheme.typography.bodySmall)
                }
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

/** What happened after a confirmed action: "Done: ..." and a short result. */
@Composable
private fun ResultCard(title: String, detail: String?, onClose: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, fontWeight = FontWeight.SemiBold)
            detail?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
            TextButton(onClick = onClose) { Text("OK") }
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
