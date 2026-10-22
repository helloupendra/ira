package io.github.helloupendra.ira.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import io.github.helloupendra.ira.IraApp
import io.github.helloupendra.ira.approvals.DeviceKey
import io.github.helloupendra.ira.core.Approvals
import io.github.helloupendra.ira.tools.Apps
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Settings, Approvals: approve once instead of at every step. Enroll this phone with the PIN
 * (a Keystore key the fingerprint unlocks), open a trust window, and trust apps.
 */
@Composable
fun ApprovalsScreen(app: IraApp, onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var enrolled by remember { mutableStateOf(app.settings.approvalsEnrolled && DeviceKey.exists()) }
    var pin by remember { mutableStateOf("") }
    var message by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var minutes by remember { mutableIntStateOf(15) }
    var trusted by remember { mutableStateOf(app.settings.trustedApps) }
    var adding by remember { mutableStateOf(false) }

    /** Run a server call off the main thread; null means it worked. */
    fun call(work: () -> String?, after: () -> Unit = {}) {
        busy = true
        message = null
        scope.launch {
            val problem = withContext(Dispatchers.IO) { work() }
            busy = false
            if (problem == null) after() else message = problem
        }
    }

    Column(Modifier.fillMaxSize()) {
        TopRow("Approvals", onBack)
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text(
                "Approve with a fingerprint instead of typing the PIN each time, and let Ira tap and type for a few " +
                    "minutes after one approval. Sending, calling, paying and deleting always ask.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            message?.let { Text(it, color = MaterialTheme.colorScheme.error) }

            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Fingerprint approval", fontWeight = FontWeight.SemiBold)
                    if (enrolled) {
                        Text("This phone is enrolled. A request that needs your PIN offers your fingerprint first.")
                        OutlinedButton(onClick = {
                            DeviceKey.delete()
                            app.settings.approvalsEnrolled = false
                            enrolled = false
                        }) { Text("Stop using the fingerprint here") }
                    } else {
                        Text("Enroll this phone once with your PIN. Its key stays in the phone's secure hardware.")
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
                            call({
                                val publicKey = DeviceKey.create()
                                app.approvals.enroll(typed, publicKey)?.also { DeviceKey.delete() }
                            }) {
                                app.settings.approvalsEnrolled = true
                                enrolled = true
                            }
                        }) { Text(if (busy) "Enrolling..." else "Enroll with PIN") }
                    }
                }
            }

            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Trust window", fontWeight = FontWeight.SemiBold)
                    Text("After one approval, screen, app and link actions run without asking again for:")
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        for (choice in Approvals.WINDOWS) {
                            FilterChip(selected = minutes == choice, onClick = { minutes = choice }, label = { Text("$choice min") })
                        }
                    }
                    Button(enabled = !busy, onClick = { call({ app.approvals.trust(minutes) }) { app.trustOpened(minutes) } }) {
                        Text("Start the trust window")
                    }
                }
            }

            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Trusted apps", fontWeight = FontWeight.SemiBold)
                    Text("In these apps Ira may tap and type without asking each time. Adding one needs your PIN.")
                    if (trusted.isEmpty()) Text("None yet.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    for (pkg in trusted.sorted()) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(Apps.label(context, pkg) ?: pkg, modifier = Modifier.weight(1f))
                            TextButton(enabled = !busy, onClick = {
                                call({ app.approvals.removeTrustedApp(pkg) }) {
                                    trusted = trusted - pkg
                                    app.settings.trustedApps = trusted
                                }
                            }) { Text("Remove") }
                        }
                    }
                    OutlinedButton(enabled = !busy, onClick = { adding = true }) { Text("Add an app") }
                }
            }
            HorizontalDivider()
        }
    }

    if (adding) {
        var chosen by remember { mutableStateOf<Apps.App?>(null) }
        var addPin by remember { mutableStateOf("") }
        val apps = remember { Apps.launchable(context).sortedBy { it.label.lowercase() } }
        AlertDialog(
            onDismissRequest = { adding = false },
            title = { Text("Trust an app") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (chosen == null) {
                        for (candidate in apps) TextButton(onClick = { chosen = candidate }) { Text(candidate.label) }
                    } else {
                        Text("Let Ira tap and type in ${chosen!!.label} without asking each time?")
                        OutlinedTextField(
                            value = addPin,
                            onValueChange = { value -> addPin = value.filter { it.isDigit() }.take(12) },
                            label = { Text("Your action PIN") },
                            singleLine = true,
                            visualTransformation = PasswordVisualTransformation(),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                        )
                    }
                }
            },
            confirmButton = {
                TextButton(enabled = chosen != null && addPin.length >= 4 && !busy, onClick = {
                    val pkg = Approvals.checkPackage(chosen!!.pkg)
                    val typed = addPin
                    adding = false
                    call({ app.approvals.addTrustedApp(pkg, typed) }) {
                        trusted = trusted + pkg
                        app.settings.trustedApps = trusted
                    }
                }) { Text("Trust it") }
            },
            dismissButton = { TextButton(onClick = { adding = false }) { Text("Cancel") } },
        )
    }
}

/** The banner while a trust window is open, with Stop. */
@Composable
fun TrustBanner(app: IraApp, secondsLeft: Long) {
    val text = Approvals.banner(secondsLeft) ?: return
    val scope = rememberCoroutineScope()
    Card(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
    ) {
        Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(text, modifier = Modifier.weight(1f))
            TextButton(onClick = {
                app.trustClosed()
                scope.launch { withContext(Dispatchers.IO) { app.approvals.stopTrust() } }
            }) { Text("Stop") }
        }
    }
}
