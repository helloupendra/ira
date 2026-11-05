package io.github.helloupendra.ira.ui

import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.width
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.sp
import java.time.LocalTime
import java.time.LocalDate
import java.time.format.DateTimeFormatter
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
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.selection.selectable
import androidx.compose.material3.RadioButton
import androidx.compose.ui.semantics.Role
import io.github.helloupendra.ira.core.Reports
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
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
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
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
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.runtime.mutableDoubleStateOf
import io.github.helloupendra.ira.core.Steps
import io.github.helloupendra.ira.core.Markup
import io.github.helloupendra.ira.core.Now
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.withStyle
import io.github.helloupendra.ira.voice.nowMs

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
    val dropItems by app.drop.items.collectAsState()
    var devices by remember { mutableStateOf<List<Now.Device>?>(null) }
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
    // Which of the person's devices are on, for Now; none shown when it can't be read.
    LaunchedEffect(refresh) {
        devices =
            withContext(Dispatchers.IO) {
                val base = app.settings.server ?: return@withContext null
                val token = app.secrets.token() ?: return@withContext null
                runCatching { Net.get(base.trimEnd('/') + Now.DEVICES_PATH, token) }.getOrNull()
                    ?.takeIf { it.status == 200 }?.let { Now.devices(it.body) }
            }
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

    // The round button: talk, stop Ira speaking, stop listening, or end the call.
    val talkTap: () -> Unit = {
        val current = session
        when {
            current == null || !ui.listening -> talk()
            ui.status == CallStatus.Speaking -> current.stopIra()
            current is PhoneSession -> current.stopListening()
            else -> app.endCall()
        }
    }
    Box(Modifier.fillMaxSize().background(Presence.colors.bg)) {
        Column(Modifier.fillMaxSize().imePadding()) {
            val live = ui.mode == TalkMode.LIVE && ui.status != CallStatus.Ended
            TalkHeader(
                ui,
                link,
                onNew = if ((lines.isNotEmpty() || ui.step != null) && !live) app::newConversation else null,
                onDrop = onDrop,
                onSkills = onSkills,
                onSettings = onSettings,
            )
            val setup = !checklistHidden && !Checklist.complete(facts) && !ui.listening
            if (setup) {
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
            Conversation(
                ui, lines, Modifier.weight(1f), greeting = !setup, onReport = { reporting = it },
                now = Now.cards(dropItems.firstOrNull(), devices), onDrop = onDrop,
            )
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
                        fingerprint@{
                            // The server signs the same bytes: the action, the summary shown, its expiry.
                            val expiresAt = card.expiresAt ?: (System.currentTimeMillis() / 1000 + (card.expiresIn ?: 120))
                            val payload =
                                runCatching { Approvals.payload(card.id, card.summary, expiresAt) }.getOrNull()
                            if (payload == null) {
                                outcome = "Your Ira sent this card in a form the phone can't sign."
                                return@fingerprint
                            }
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
                    color = Presence.colors.down,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp),
                )
            }
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
                    Text(error, color = Presence.colors.down, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                    TextButton(onClick = { send() }, enabled = !sending) { Text("Retry") }
                }
            }
            val active = ui.listening && ui.status != CallStatus.Ended
            AskPill(
                value = typed,
                onValueChange = {
                    typed = it
                    sendError = null
                },
                placeholder = "Ask ${ui.assistant} anything, or just start talking…",
                micIcon = painterResource(if (active) R.drawable.ic_stop else R.drawable.ic_mic),
                sendIcon = painterResource(R.drawable.ic_send),
                micLabel = when {
                    !active -> "Talk: talk to Ira"
                    ui.status == CallStatus.Speaking -> "Stop: talk to Ira"
                    else -> "End: talk to Ira"
                },
                onMic = talkTap,
                onSend = { send() },
                sending = sending,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
            )
        }
        // Listening fills the screen while Ira's turn is the person's, unless an action waits.
        if (ui.listening && ui.status != CallStatus.Ended && ui.action == null) {
            ListeningView(
                ui = ui,
                lastAnswer = lines.lastOrNull { it.fromIra }?.text,
                question = lines.lastOrNull { !it.fromIra }?.text,
                onCancel = { app.endCall() },
                onDone = talkTap,
            )
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
    val colors = Presence.colors
    // At most about half a phone's height: its steps scroll inside, so the ask pill stays in view.
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp).heightIn(max = 380.dp).presenceCard(colors, radius = 16.dp)) {
        Row(Modifier.padding(start = 16.dp, end = 8.dp, top = 8.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Get Ira ready", fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = colors.ink)
                Text("${steps.count { it.done }} of ${steps.size} done", fontSize = 12.sp, color = colors.muted)
            }
            TextButton(onClick = onHide) { Text("Hide", color = colors.muted) }
        }
        Column(Modifier.verticalScroll(rememberScrollState())) {
        for (step in steps) {
            Hairline()
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                StepMark(step.done)
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(step.title, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = if (step.done) colors.muted else colors.ink)
                    if (!step.done) {
                        Text(step.detail, fontSize = 13.sp, lineHeight = 18.sp, color = colors.muted)
                        Box(Modifier.padding(top = 6.dp)) {
                            PillButton(if (refused(step.action)) "Open settings" else step.button, { onAction(step.action) }, compact = true)
                        }
                        if (refused(step.action)) {
                            Text(
                                "Android remembers your earlier No. In the settings that open, choose Permissions (or Notifications) and allow it for Ira.",
                                fontSize = 12.sp,
                                lineHeight = 17.sp,
                                color = colors.muted,
                            )
                        }
                    }
                }
            }
        }
        }
    }
}

/** A step's mark: a hollow ring to do, a filled green dot with a tick when done. */
@Composable
private fun StepMark(done: Boolean) {
    val colors = Presence.colors
    Box(
        Modifier
            .padding(top = 1.dp)
            .size(20.dp)
            .clip(CircleShape)
            .background(if (done) colors.greenDeep else Color.Transparent)
            .border(BorderStroke(1.5.dp, if (done) colors.greenDeep else colors.faint), CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        if (done) Text("✓", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = Color.White)
    }
}

/** "Ira" with what is happening under it, and New (once there is a conversation), Drop, Skills and Settings as icons. */
@Composable
private fun TalkHeader(
    ui: CallUi,
    link: LinkState,
    onNew: (() -> Unit)?,
    onDrop: () -> Unit,
    onSkills: () -> Unit,
    onSettings: () -> Unit,
) {
    val text =
        when (ui.status) {
            CallStatus.Off -> "Tap the mic or type"
            CallStatus.Connecting -> "Connecting..."
            CallStatus.Listening -> if (ui.listening) "Listening" else "Tap the mic or type"
            CallStatus.Hearing -> "Hearing you"
            CallStatus.Thinking -> if (ui.step == null) "Answering" else "Thinking"
            CallStatus.Speaking -> "Speaking. Talk to interrupt."
            CallStatus.Reconnecting -> "Reconnecting..."
            CallStatus.Ended -> "Call ended"
        }
    val tools = if (link is LinkState.Connected) "phone tools on" else "phone tools off"
    // Which way Ira hears: the server (a live call) or the phone's own recognition.
    val mode =
        when {
            ui.mode == TalkMode.LIVE && ui.status != CallStatus.Ended -> "Live call · "
            ui.mode == TalkMode.PHONE -> "Phone recognition · "
            else -> ""
        }
    val colors = Presence.colors
    Row(
        Modifier.fillMaxWidth().padding(start = 20.dp, end = 6.dp, top = 6.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                // Green while this phone's link to Ira is up.
                Box(Modifier.size(8.dp).clip(CircleShape).background(if (link is LinkState.Connected) colors.green else colors.faint))
                Text(ui.assistant, fontSize = 20.sp, fontWeight = FontWeight.SemiBold, color = colors.ink)
            }
            Text("$mode$text · $tools", fontSize = 12.sp, color = colors.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        onNew?.let { IconAction(R.drawable.ic_new, "New", it, tint = colors.muted) }
        IconAction(R.drawable.ic_drop, "Drop", onDrop, tint = colors.muted)
        IconAction(R.drawable.ic_skills, "Skills", onSkills, tint = colors.muted)
        IconAction(R.drawable.ic_settings, "Settings", onSettings, tint = colors.muted)
    }
}

@Composable
private fun Conversation(
    ui: CallUi,
    lines: List<Transcript.Line>,
    modifier: Modifier,
    greeting: Boolean,
    onReport: (Transcript.Line) -> Unit,
    now: List<Now.Card> = emptyList(),
    onDrop: () -> Unit = {},
) {
    val list = rememberLazyListState()
    val pending = ui.step != null
    val count = lines.size + 1 + (if (ui.caption.isNotBlank()) 1 else 0) + (if (pending) 1 else 0)
    LaunchedEffect(count, lines.lastOrNull()?.text?.length, ui.stepsDone.size) { list.animateScrollToItem(count - 1) }
    LazyColumn(
        state = list,
        modifier = modifier.fillMaxWidth().padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp),
    ) {
        item { Spacer(Modifier.height(8.dp)) }
        // The greeting, unless the setup checklist is showing above.
        if (greeting && lines.isEmpty() && ui.caption.isBlank()) item { Hero(now, onDrop) }
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
        if (pending) item(key = "pending") { PendingRow(ui) }
    }
}

/** An empty conversation: the lens at rest, the greeting, the day, and Now (or a hint when there is none). */
@Composable
private fun Hero(now: List<Now.Card>, onDrop: () -> Unit) {
    val colors = Presence.colors
    val greeting =
        buildAnnotatedString {
            append("Good ")
            withStyle(SpanStyle(fontStyle = FontStyle.Italic, color = colors.green)) { append(Now.partOfDay(LocalTime.now().hour)) }
            append(".")
        }
    Column(Modifier.fillMaxWidth().padding(top = 40.dp, bottom = 16.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Lens(104.dp, breathing = true, rings = 1)
        Spacer(Modifier.height(20.dp))
        Text(greeting, fontFamily = Presence.serif, fontSize = 34.sp, color = colors.ink)
        Spacer(Modifier.height(6.dp))
        Text(LocalDate.now().format(DateTimeFormatter.ofPattern("EEEE, d MMMM")), fontSize = 14.sp, color = colors.muted)
        Spacer(Modifier.height(22.dp))
        if (now.isEmpty()) {
            Text(
                "Ask in your own words, in any language. Try “kal ka calendar batao”.",
                fontSize = 13.sp,
                color = colors.faint,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(horizontal = 24.dp),
            )
        } else {
            Column(Modifier.fillMaxWidth().padding(horizontal = 4.dp).presenceCard(colors, radius = 16.dp)) {
                now.forEachIndexed { index, card ->
                    if (index > 0) Hairline()
                    NowCard(card, onClick = if (card.opens == Now.Opens.DROP) onDrop else null)
                }
            }
        }
    }
}

/** One Now row: a label with a green dot, one line of value, one muted line. */
@Composable
private fun NowCard(card: Now.Card, onClick: (() -> Unit)?) {
    val colors = Presence.colors
    Column(
        Modifier
            .fillMaxWidth()
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(7.dp)) {
            Box(Modifier.size(5.dp).clip(CircleShape).background(colors.green))
            Text(card.label.uppercase(), style = Presence.label, color = colors.faint)
        }
        Text(card.value, fontSize = 14.sp, color = colors.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Text(card.detail, fontSize = 12.sp, color = colors.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** An answer's Markdown as styled text. */
private fun styled(text: String): AnnotatedString =
    buildAnnotatedString {
        for (span in Markup.spans(text)) {
            withStyle(
                SpanStyle(
                    fontWeight = if (span.bold) FontWeight.SemiBold else null,
                    fontStyle = if (span.italic) FontStyle.Italic else null,
                    fontFamily = if (span.code) FontFamily.Monospace else null,
                ),
            ) { append(span.text) }
        }
    }

@Composable
private fun Bubble(line: Transcript.Line, onReport: (Transcript.Line) -> Unit) {
    val colors = Presence.colors
    val mine = !line.fromIra
    val reportable = line.fromIra && line.messageId != null
    val text = if (line.stopped) line.text + " (stopped)" else line.text
    if (mine) {
        val shape = RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp, bottomEnd = 6.dp, bottomStart = 18.dp)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            Box(
                Modifier
                    .widthIn(max = 300.dp)
                    .clip(shape)
                    .background(colors.raised)
                    .border(BorderStroke(1.dp, colors.line), shape)
                    .padding(horizontal = 16.dp, vertical = 10.dp),
            ) {
                Text(text, fontSize = 16.sp, color = colors.ink)
            }
        }
        return
    }
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
        Lens(30.dp)
        Spacer(Modifier.width(12.dp))
        Text(
            styled(text),
            fontSize = 16.sp,
            lineHeight = 25.sp,
            color = colors.ink,
            modifier =
                Modifier
                    .weight(1f)
                    .padding(top = 3.dp)
                    .then(
                        if (reportable) {
                            Modifier.combinedClickable(onClick = {}, onLongClick = { onReport(line) }, onLongClickLabel = "Report this answer")
                        } else {
                            Modifier
                        },
                    ),
        )
        if (reportable) {
            Text(
                "⋮",
                style = MaterialTheme.typography.titleMedium,
                color = colors.faint,
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

/** Listening, over the whole screen: the large lens on the voice, what Ira hears, Cancel and Done. */
@Composable
private fun ListeningView(ui: CallUi, lastAnswer: String?, onCancel: () -> Unit, onDone: () -> Unit, question: String? = null) {
    val colors = Presence.colors
    val label =
        when (ui.status) {
            CallStatus.Hearing -> "Hearing you"
            CallStatus.Thinking -> "Thinking"
            CallStatus.Speaking -> "Speaking"
            CallStatus.Connecting, CallStatus.Reconnecting -> "Connecting"
            else -> "Listening"
        }
    Box(
        Modifier
            .fillMaxSize()
            .background(colors.bg)
            .background(
                Brush.radialGradient(
                    listOf(Color(0xFF1F6F5C).copy(alpha = if (colors.dark) 0.22f else 0.12f), Color.Transparent),
                ),
            )
            // Taps stay here, never reach the conversation underneath.
            .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {},
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.padding(24.dp)) {
            val speaking = ui.status == CallStatus.Speaking
            val working = ui.status == CallStatus.Thinking || (ui.step != null && !speaking)
            Lens(
                160.dp,
                // Her voice plays through the phone's player: a steady level keeps the bars moving.
                level = if (speaking) 0.04f else ui.level,
                rings = 2,
                heartbeat = ui.status == CallStatus.Listening || ui.status == CallStatus.Hearing,
                thinking = working,
            )
            Spacer(Modifier.height(22.dp))
            Text(label.uppercase(), style = Presence.label, color = colors.green)
            if (working) {
                Spacer(Modifier.height(8.dp))
                StepLine(ui.step ?: Steps.THINKING, ui.askedAt)
            }
            Spacer(Modifier.height(14.dp))
            when {
                ui.caption.isNotBlank() ->
                    Text("“${ui.caption}”", fontFamily = Presence.serif, fontSize = 28.sp, lineHeight = 34.sp, color = colors.ink, textAlign = TextAlign.Center)
                // In place of "Speak now" or Ira's answer: the microphone gives nothing.
                ui.micSilent -> SilentMic(ui.micName)
                ui.status == CallStatus.Speaking && !lastAnswer.isNullOrBlank() ->
                    Text(lastAnswer, fontSize = 16.sp, lineHeight = 24.sp, color = colors.muted, textAlign = TextAlign.Center, maxLines = 6)
                // The question that was taken, while Ira works on it.
                ui.status == CallStatus.Thinking && !question.isNullOrBlank() ->
                    Text("“$question”", fontFamily = Presence.serif, fontSize = 24.sp, lineHeight = 30.sp, color = colors.muted, textAlign = TextAlign.Center, maxLines = 3)
                else -> Text("Speak now", fontFamily = Presence.serif, fontSize = 28.sp, color = colors.faint)
            }
            Spacer(Modifier.height(26.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                PillButton("Cancel", onCancel)
                PillButton(if (ui.status == CallStatus.Speaking) "Stop" else "Done", onDone, filled = true)
            }
        }
    }
}

/** What Ira is doing, in words, with its seconds once it has taken 3. */
@Composable
private fun StepLine(step: String, since: Double?) {
    var now by remember { mutableDoubleStateOf(nowMs()) }
    LaunchedEffect(since) {
        while (true) {
            delay(1000)
            now = nowMs()
        }
    }
    val seconds = since?.let { ((now - it) / 1000).toInt() } ?: 0
    Text(Steps.line(step, seconds), fontSize = 14.sp, color = Presence.colors.muted, textAlign = TextAlign.Center)
}

/** The answer on its way, in the chat: the lens rippling, the step, and each tool done so far. */
@Composable
private fun PendingRow(ui: CallUi) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Lens(30.dp, thinking = true)
            StepLine(ui.step ?: Steps.THINKING, ui.askedAt)
        }
        if (ui.stepsDone.isNotEmpty()) {
            FlowRow(Modifier.padding(start = 42.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                ui.stepsDone.forEach { ReceiptChip(it) }
            }
        }
    }
}

/** The microphone gave nothing for 3 s: say so, and where to look. */
@Composable
private fun SilentMic(input: String) {
    val context = LocalContext.current
    val colors = Presence.colors
    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(
            "Ira hears nothing from $input. Check that Ira may use the microphone (Settings → Apps → Ira → Permissions), and that microphone access is on.",
            fontSize = 15.sp,
            lineHeight = 22.sp,
            color = colors.warn,
            textAlign = TextAlign.Center,
        )
        PillButton("Open Ira's settings", { openAppSettings(context) })
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
    val colors = Presence.colors
    Card(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
        colors = CardDefaults.cardColors(containerColor = colors.warn.copy(alpha = 0.06f), contentColor = colors.ink),
        border = BorderStroke(1.dp, colors.warn.copy(alpha = 0.55f)),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            DotLabel(if (card.needsPin) "Waiting for your PIN" else "Waiting for you", colors.warn)
            Text(card.summary, fontSize = 16.sp, color = colors.ink)
            if (card.needsPin) {
                onFingerprint?.let { approve ->
                    PillButton("Approve with fingerprint", approve, filled = true, enabled = !busy)
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
                    PillButton("Not now", onDismiss)
                    PillButton(
                        if (busy) "Checking..." else "Confirm",
                        onClick = {
                            val typedPin = pin
                            pin = ""
                            onPin(typedPin)
                        },
                        filled = true,
                        enabled = !busy && pin.length >= 4,
                    )
                }
            } else {
                Text("Say \"haan\" or \"yes\", or tap.", style = MaterialTheme.typography.bodySmall)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    PillButton("No", onNo)
                    PillButton("Yes", onYes, filled = true, enabled = card.canApprove)
                }
            }
            outcome?.let { Text(it, color = colors.down, style = MaterialTheme.typography.bodyMedium) }
        }
    }
}

/** What happened after a confirmed action: "Done: ..." and a short result. */
@Composable
private fun ResultCard(title: String, detail: String?, onClose: () -> Unit) {
    val colors = Presence.colors
    Column(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp).presenceCard(colors, radius = 16.dp).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        DotLabel(if (title.startsWith("Done")) "Done" else "Result")
        Text(title, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = colors.ink)
        detail?.let { Text(it, fontSize = 14.sp, color = colors.muted) }
        Box(Modifier.padding(top = 4.dp)) { PillButton("OK", onClose, compact = true) }
    }
}
