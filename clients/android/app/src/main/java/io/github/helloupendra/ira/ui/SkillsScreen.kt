package io.github.helloupendra.ira.ui

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
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
import io.github.helloupendra.ira.core.Permissions
import io.github.helloupendra.ira.core.Skills
import io.github.helloupendra.ira.core.SpecialAccess
import io.github.helloupendra.ira.core.ToolGate
import io.github.helloupendra.ira.tools.ScreenAccess

/** The SMS and call-log permissions: on Google Play, asked for only once Ira is the assistant. */
private val RESTRICTED = setOf(Permissions.READ_CALL_LOG, Permissions.READ_SMS, Permissions.SEND_SMS)

@Composable
fun SkillsScreen(app: IraApp, onBack: () -> Unit) {
    val context = LocalContext.current
    val skillsOn by app.skillsOn.collectAsState()
    var refresh by remember { mutableIntStateOf(0) }
    var asking by remember { mutableStateOf<String?>(null) }
    LifecycleResumeEffect(Unit) {
        refresh++
        onPauseOrDispose { }
    }
    val request =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { refresh++ }

    // Read fresh on each refresh (after a permission prompt, or back from Android's settings).
    val state = remember(refresh) { app.tools.gateState() }
    val flavor = app.tools.flavor
    val tools = app.tools.tools
    val server = app.settings.server.orEmpty().removePrefix("https://").removePrefix("http://")

    fun wanted(skill: String): List<String> {
        val all = tools.filter { it.skill == skill }.flatMap { it.permissions + it.optionalPermissions }.distinct()
        return all.filter { flavor == Flavor.PERSONAL || it !in RESTRICTED || state.assistantRole }
            .filter { it !in state.granted }
    }

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
            val skills = tools.map { it.skill }.distinct()
            for (skill in skills) {
                val specs = tools.filter { it.skill == skill }
                val missing = wanted(skill)
                val special = specs.flatMap { it.special }.distinct().filter { it !in state.special }
                val needsRole = flavor == Flavor.PLAY && specs.any { it.restricted } && !state.assistantRole
                SkillCard(
                    title = Disclosures.skillTitle(skill),
                    about = Skills.about[skill].orEmpty(),
                    onServer = skill in skillsOn,
                    needsRole = needsRole,
                    missing = missing.map { ToolGate.label(it) },
                    special = special,
                    onAllow = { asking = skill },
                    onSpecial = { access -> openSpecial(context, access) },
                    extra = {
                        if (skill == Skills.REMINDERS && SpecialAccess.EXACT_ALARMS !in state.special) {
                            TextButton(onClick = { openSpecial(context, SpecialAccess.EXACT_ALARMS) }) { Text("Allow reminders on time") }
                        }
                        if (skill == Skills.SETTINGS && SpecialAccess.DO_NOT_DISTURB !in state.special) {
                            TextButton(onClick = { openSpecial(context, SpecialAccess.DO_NOT_DISTURB) }) { Text("Allow Do Not Disturb") }
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
                val missing = wanted(skill)
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
                        "Ira can then also start calls and apps for you while it is in the background."
                },
                style = MaterialTheme.typography.bodyMedium,
            )
            if (!held) OutlinedButton(onClick = onOpen) { Text("Open the setting") }
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
            if (needsRole) {
                Text(
                    "Google Play lets an app read calls and SMS only while it is the digital assistant: switch that on above first.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (missing.isNotEmpty()) {
                Text("The phone has not allowed: ${missing.joinToString(", ")}.", style = MaterialTheme.typography.bodySmall)
                OutlinedButton(onClick = onAllow) { Text("Allow") }
            }
            for (access in special) {
                if (access == SpecialAccess.ACCESSIBILITY) {
                    OutlinedButton(onClick = onAllow) { Text("Switch on (read the warning first)") }
                } else {
                    OutlinedButton(onClick = { onSpecial(access) }) { Text("Switch on ${ToolGate.specialLabel(access)}") }
                }
            }
            if (missing.isEmpty() && special.isEmpty() && !needsRole) {
                Text("The phone allows it.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
            }
            extra()
        }
    }
}

private fun openAssistantSettings(context: Context) {
    val tries = listOf(Intent(Settings.ACTION_VOICE_INPUT_SETTINGS), Intent(Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS), Intent(Settings.ACTION_SETTINGS))
    for (intent in tries) {
        try {
            context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            return
        } catch (_: Exception) {
        }
    }
}

private fun openSpecial(context: Context, access: SpecialAccess) {
    val intent =
        when (access) {
            SpecialAccess.NOTIFICATION_LISTENER -> Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)
            SpecialAccess.ACCESSIBILITY -> Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
            SpecialAccess.EXACT_ALARMS ->
                if (Build.VERSION.SDK_INT >= 31) {
                    Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:${context.packageName}"))
                } else {
                    return
                }
            SpecialAccess.DO_NOT_DISTURB -> Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS)
        }
    try {
        context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    } catch (_: Exception) {
    }
}
