package io.github.helloupendra.ira.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LifecycleResumeEffect
import io.github.helloupendra.ira.IraApp
import io.github.helloupendra.ira.core.Flavor
import io.github.helloupendra.ira.core.Skills
import io.github.helloupendra.ira.core.SpecialAccess
import io.github.helloupendra.ira.core.ToolGate
import io.github.helloupendra.ira.tools.ScreenAccess

@Composable
fun SkillsScreen(app: IraApp, onBack: () -> Unit) {
    val context = LocalContext.current
    val skillsOn by app.skillsOn.collectAsState()
    var refresh by remember { mutableIntStateOf(0) }
    var asking by remember { mutableStateOf<String?>(null) }
    var explaining by remember { mutableStateOf<SpecialAccess?>(null) }
    LifecycleResumeEffect(Unit) {
        refresh++
        onPauseOrDispose { }
    }
    val request = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { refresh++ }

    // Read fresh on each refresh (after a permission prompt, or back from Android's settings).
    val state = remember(refresh) { app.tools.gateState() }
    val tools = app.tools.tools
    val server = app.settings.server.orEmpty().removePrefix("https://").removePrefix("http://")

    Column(Modifier.fillMaxSize()) {
        TopRow("Skills", onBack)
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                "A skill works when two things are true: you switched it on for this phone on your Ira " +
                    "(Your devices, with your PIN), and the phone allows it here.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            AssistantCard(state.assistantRole) { openAssistantSettings(context) }
            if (app.tools.flavor == Flavor.PLAY_LITE) {
                Text(
                    "This version of Ira can't read your call history or SMS. It can still place calls, look up " +
                        "contacts, and read and answer notifications.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            for (skill in tools.map { it.skill }.distinct()) {
                val specs = tools.filter { it.skill == skill }
                val needsRole = app.tools.flavor.play && specs.any { it.restricted } && !state.assistantRole
                SkillCard(
                    title = Disclosures.skillTitle(skill),
                    about = Skills.about[skill].orEmpty(),
                    onServer = skill in skillsOn,
                    needsRole = needsRole,
                    missing = missingPermissions(app, state, skill).map { ToolGate.label(it) },
                    special = missingSpecial(app, state, skill),
                    onAllow = { asking = skill },
                    onOpenSettings = { openAppSettings(context) },
                    onSpecial = { access -> if (access == SpecialAccess.ACCESSIBILITY) asking = skill else explaining = access },
                    extra = {
                        if (skill == Skills.REMINDERS && SpecialAccess.EXACT_ALARMS !in state.special) {
                            TextButton(onClick = { explaining = SpecialAccess.EXACT_ALARMS }) { Text("Allow reminders on time") }
                        }
                        if (skill == Skills.SETTINGS && SpecialAccess.DO_NOT_DISTURB !in state.special) {
                            TextButton(onClick = { explaining = SpecialAccess.DO_NOT_DISTURB }) { Text("Allow Do Not Disturb") }
                        }
                    },
                )
            }
        }
    }

    asking?.let { skill ->
        val text = Disclosures.skill(skill, server)
        val go = {
            asking = null
            if (skill == Skills.SCREEN) {
                app.settings.screenWarningAccepted = true
                ScreenAccess.openSettings(context)
            } else {
                val missing = missingPermissions(app, state, skill)
                if (missing.isNotEmpty()) request.launch(missing.toTypedArray())
            }
        }
        if (text == null) {
            go()
        } else {
            AlertDialog(
                onDismissRequest = { asking = null },
                title = { Text(Disclosures.skillTitle(skill)) },
                text = { Text(text) },
                confirmButton = { TextButton(onClick = go) { Text(if (skill == Skills.SCREEN) "I understand, switch it on" else "Agree") } },
                dismissButton = { TextButton(onClick = { asking = null }) { Text("Not now") } },
            )
        }
    }

    explaining?.let { access ->
        AlertDialog(
            onDismissRequest = { explaining = null },
            title = { Text(ToolGate.specialLabel(access)) },
            text = { Text(specialWhy(access)) },
            confirmButton = {
                TextButton(onClick = {
                    explaining = null
                    openSpecial(context, access)
                }) { Text("Open settings") }
            },
            dismissButton = { TextButton(onClick = { explaining = null }) { Text("Not now") } },
        )
    }
}

@Composable
private fun AssistantCard(held: Boolean, onOpen: () -> Unit) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Digital assistant", fontWeight = FontWeight.SemiBold)
            Text(
                if (held) {
                    "Ira is this phone's digital assistant: a long press of the power button opens Ira."
                } else {
                    "Make Ira the phone's digital assistant so a long press of the power button opens Ira. " +
                        "Ira can then also start calls and apps for you while it is in the background. " +
                        "In the settings that open, choose Digital assistant app, then Ira."
                },
                style = MaterialTheme.typography.bodyMedium,
            )
            if (!held) OutlinedButton(onClick = onOpen) { Text("Open settings") }
        }
    }
}

@Composable
private fun SkillCard(
    title: String,
    about: String,
    onServer: Boolean,
    needsRole: Boolean,
    missing: List<String>,
    special: List<SpecialAccess>,
    onAllow: () -> Unit,
    onOpenSettings: () -> Unit,
    onSpecial: (SpecialAccess) -> Unit,
    extra: @Composable () -> Unit,
) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row {
                Text(title, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                Text(
                    if (onServer) "On for this phone" else "Off on your Ira",
                    style = MaterialTheme.typography.labelMedium,
                    color = if (onServer) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(about, style = MaterialTheme.typography.bodyMedium)
            if (!onServer) {
                Text(
                    "To use it, switch it on for this phone on your Ira's Your devices page (it needs your PIN).",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (needsRole) {
                Text(
                    "Google Play lets an app read calls and SMS only while it is the digital assistant: make Ira the assistant above first.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (missing.isNotEmpty()) {
                Text("Android has not allowed: ${missing.joinToString(", ")}.", style = MaterialTheme.typography.bodySmall)
                Row {
                    OutlinedButton(onClick = onAllow) { Text("Allow") }
                    TextButton(onClick = onOpenSettings) { Text("Open settings") }
                }
                Text(
                    "If Allow does nothing, Android remembers an earlier No: use Open settings, then Permissions.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            for (access in special) {
                OutlinedButton(onClick = { onSpecial(access) }) {
                    Text(if (access == SpecialAccess.ACCESSIBILITY) "Switch on (read the warning first)" else "Switch on ${ToolGate.specialLabel(access)}")
                }
            }
            if (missing.isEmpty() && special.isEmpty() && !needsRole) {
                Text("Android allows it.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
            }
            extra()
        }
    }
}
