package io.github.helloupendra.ira.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.ProvideTextStyle
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.helloupendra.ira.IraApp
import io.github.helloupendra.ira.approvals.DeviceKey
import io.github.helloupendra.ira.core.Approvals
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Settings, Approvals: fewer PINs for one task (docs/security.md). After a PIN on a screen or
 * app action, a window lets the next such steps on this phone run without asking; it can be
 * stopped here at any time. How long it lasts is set on the person's Ira (it needs a sign-in).
 */
@Composable
fun ApprovalsScreen(app: IraApp, onBack: () -> Unit) {
    val context = LocalContext.current
    val status by app.approvals.collectAsState()
    var message by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) { app.refreshApprovals() }
    val now = System.currentTimeMillis() / 1000.0

    val colors = Presence.colors
    Column(Modifier.fillMaxSize()) {
        ScreenHeader("Approvals", onBack)
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(24.dp),
        ) {
            Text(
                "When you confirm a screen or app action on this phone with your PIN, Ira may do the next such " +
                    "steps here (open an app or a link, play, tap and type) without asking again, for a while. " +
                    "Sending, replying, calling, paying, deleting and new permissions always ask.",
                fontSize = 14.sp,
                lineHeight = 20.sp,
                color = colors.muted,
                modifier = Modifier.padding(horizontal = 4.dp),
            )
            message?.let { Text(it, color = colors.down, fontSize = 14.sp, modifier = Modifier.padding(horizontal = 4.dp)) }
            Section("How long") {
                ItemRow(
                    when (val minutes = status?.minutes) {
                        null -> "Asking your Ira..."
                        0 -> "Off: every step asks for your PIN."
                        else -> "$minutes minutes after each PIN."
                    },
                )
                Hairline()
                ItemRow("Change it on your Ira", "Your assistant", onClick = { open(context, app.settings.server.orEmpty()) }) { Chevron() }
            }
            Section("Open now") {
                val open = status?.windows.orEmpty().filter { it.expiresAt > now }
                if (open.isEmpty()) ItemRow("None.", titleColor = colors.muted)
                open.forEachIndexed { index, window ->
                    if (index > 0) Hairline()
                    ItemRow(
                        window.device.ifBlank { "A device" },
                        (Approvals.banner(window.secondsLeft(now)) ?: "Closing") + " · ${window.steps} steps so far",
                    ) { PillButton("Stop", { app.stopApproval(window.id) { message = it } }, compact = true) }
                }
                if (open.size > 1) {
                    Hairline()
                    ItemRow("Stop them all", onClick = { app.stopApproval(null) { message = it } }, titleColor = colors.down)
                }
            }
            Section(
                "Trusted apps on this phone",
                note = "In these apps Ira may tap and type without asking, once it has seen the app in front. Sending, calling, paying and deleting still ask.",
            ) {
                val apps = status?.trustedOn(app.settings.deviceId).orEmpty()
                if (apps.isEmpty()) ItemRow("None.", titleColor = colors.muted)
                apps.forEachIndexed { index, pkg ->
                    if (index > 0) Hairline()
                    ItemRow(io.github.helloupendra.ira.tools.Apps.label(context, pkg) ?: pkg)
                }
                Hairline()
                // Changing them needs a sign-in (and the PIN to add one): the Ira app on the web.
                ItemRow("Add or remove them on your Ira", "Your assistant, Trusted apps", onClick = { open(context, app.settings.server.orEmpty()) }) { Chevron() }
            }
            if (Approvals.FINGERPRINT) FingerprintCard(app) { message = it }
            Spacer(Modifier.height(8.dp))
        }
    }
}

/** Fingerprint approval: enroll this phone's key once, with the PIN (behind Approvals.FINGERPRINT). */
@Composable
private fun FingerprintCard(app: IraApp, onMessage: (String?) -> Unit) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    // A fingerprint added since enrolling voids the key: then it is not enrolled any more.
    var enrolled by remember { mutableStateOf(app.settings.approvalsEnrolled && DeviceKey.usable()) }
    var pin by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    Section("Fingerprint") {
      ProvideTextStyle(TextStyle(fontSize = 14.sp, lineHeight = 20.sp, color = Presence.colors.ink)) {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (enrolled) {
                Text("This phone is enrolled: a request that needs your PIN offers your fingerprint first.")
                PillButton("Stop using the fingerprint here", {
                    DeviceKey.delete()
                    app.settings.approvalsEnrolled = false
                    enrolled = false
                }, compact = true)
            } else {
                if (app.settings.approvalsEnrolled) {
                    Text(
                        "A fingerprint was added to this phone since it was enrolled, so its key stopped working. Enroll it again.",
                        color = MaterialTheme.colorScheme.error,
                    )
                }
                Text("Enroll this phone once with your PIN. Its key stays in the phone's secure hardware. Only a fingerprint unlocks it, never the screen lock.")
                OutlinedTextField(
                    value = pin,
                    onValueChange = { value -> pin = value.filter { it.isDigit() }.take(12) },
                    label = { Text("Your action PIN") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                    modifier = Modifier.fillMaxWidth(),
                )
                Button(enabled = pin.length >= 4 && !busy, onClick = {
                    val typed = pin
                    pin = ""
                    DeviceKey.unsupported(context)?.let { return@Button onMessage(it) }
                    busy = true
                    scope.launch {
                        val problem =
                            withContext(Dispatchers.IO) {
                                try {
                                    val publicKey = DeviceKey.create()
                                    app.enrollKey(publicKey, typed)?.also { DeviceKey.delete() }
                                } catch (exc: Exception) {
                                    DeviceKey.delete()
                                    "This phone could not make an approval key. Approve with your PIN."
                                }
                            }
                        busy = false
                        if (problem == null) {
                            app.settings.approvalsEnrolled = true
                            enrolled = true
                        }
                        onMessage(problem)
                    }
                }) { Text(if (busy) "Enrolling..." else "Enroll with PIN") }
            }
        }
      }
    }
}

/** The banner while this phone's approval window is open, with Stop. */
@Composable
fun ApprovalBanner(app: IraApp, windowId: String, secondsLeft: Long) {
    val text = Approvals.banner(secondsLeft) ?: return
    Card(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
    ) {
        Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(text, modifier = Modifier.weight(1f))
            TextButton(onClick = { app.stopApproval(windowId) }) { Text("Stop") }
        }
    }
}
