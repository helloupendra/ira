package io.github.helloupendra.ira.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
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
        ScreenHeader("Skills", onBack)
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(24.dp),
        ) {
            Text(
                "A skill works when two things are true: you switched it on for this phone on your Ira " +
                    "(Your devices, with your PIN), and the phone allows it here.",
                fontSize = 14.sp,
                lineHeight = 20.sp,
                color = Presence.colors.muted,
                modifier = Modifier.padding(horizontal = 4.dp),
            )
            Section("Digital assistant") { AssistantCard(state.assistantRole) { openAssistantSettings(context) } }
            val skills = tools.map { it.skill }.distinct()
            Section(
                "Skills",
                note =
                    if (app.tools.flavor == Flavor.PLAY_LITE) {
                        "This version of Ira can't read your call history or SMS. It can still place calls, look up " +
                            "contacts, and read and answer notifications."
                    } else {
                        null
                    },
            ) {
              skills.forEachIndexed { index, skill ->
                if (index > 0) Hairline()
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
                            PillButton("Allow reminders on time", { explaining = SpecialAccess.EXACT_ALARMS }, compact = true)
                        }
                        if (skill == Skills.SETTINGS && SpecialAccess.DO_NOT_DISTURB !in state.special) {
                            PillButton("Allow Do Not Disturb", { explaining = SpecialAccess.DO_NOT_DISTURB }, compact = true)
                        }
                    },
                )
              }
            }
            Spacer(Modifier.height(8.dp))
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

/** Whether Ira is the phone's digital assistant, and the way to make it one. */
@Composable
private fun AssistantCard(held: Boolean, onOpen: () -> Unit) {
    ItemRow(
        "Ira as the phone's assistant",
        if (held) {
            "A long press of the power button opens Ira."
        } else {
            "Make Ira the phone's digital assistant so a long press of the power button opens Ira. " +
                "Ira can then also start calls and apps for you while it is in the background. " +
                "In the settings that open, choose Digital assistant app, then Ira."
        },
        onClick = if (held) null else onOpen,
    ) {
        if (held) StatusChip("On") else PillButton("Open settings", onOpen, compact = true)
    }
}

/**
 * One skill, as a row of its card: the name in bold with whether it is on for this phone, what
 * it does, and what Android still has to allow, with the buttons that ask for it.
 */
@OptIn(ExperimentalLayoutApi::class)
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
    val colors = Presence.colors
    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(title, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = colors.ink, modifier = Modifier.weight(1f))
            if (onServer) StatusChip("On for this phone") else StatusChip("Off on your Ira", colors.faint)
        }
        Text(about, fontSize = 13.sp, lineHeight = 18.sp, color = colors.muted)
        if (!onServer) {
            Note("To use it, switch it on for this phone on your Ira's Your devices page (it needs your PIN).")
        }
        if (needsRole) {
            Note("Google Play lets an app read calls and SMS only while it is the digital assistant: make Ira the assistant above first.")
        }
        if (missing.isNotEmpty()) {
            Note("Android has not allowed: ${missing.joinToString(", ")}.", colors.warn)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                PillButton("Allow", onAllow, filled = true, compact = true)
                PillButton("Open settings", onOpenSettings, compact = true)
            }
            Note("If Allow does nothing, Android remembers an earlier No: use Open settings, then Permissions.")
        }
        if (special.isNotEmpty()) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                for (access in special) {
                    PillButton(
                        if (access == SpecialAccess.ACCESSIBILITY) "Switch on (read the warning first)" else "Switch on ${ToolGate.specialLabel(access)}",
                        { onSpecial(access) },
                        compact = true,
                    )
                }
            }
        }
        if (missing.isEmpty() && special.isEmpty() && !needsRole) {
            Text("Android allows it.", fontSize = 12.sp, fontWeight = FontWeight.Medium, color = if (colors.dark) colors.green else colors.greenDeep)
        }
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) { extra() }
    }
}

/** A short muted line under a skill. */
@Composable
private fun Note(text: String, color: androidx.compose.ui.graphics.Color = Presence.colors.muted) {
    Text(text, fontSize = 12.sp, lineHeight = 17.sp, color = color)
}
