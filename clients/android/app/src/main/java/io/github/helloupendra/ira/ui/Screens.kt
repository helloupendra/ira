package io.github.helloupendra.ira.ui

import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import io.github.helloupendra.ira.BuildConfig
import io.github.helloupendra.ira.IraApp
import io.github.helloupendra.ira.core.PairError
import io.github.helloupendra.ira.core.Pairing
import io.github.helloupendra.ira.core.Plain
import io.github.helloupendra.ira.device.LinkState
import io.github.helloupendra.ira.net.Net
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class Screen { Talk, Skills, Settings }

/** The privacy policy: the project's own privacy page. */
const val PRIVACY_URL = "https://helloupendra.github.io/ira/docs/privacy/"

@Composable
fun IraScreens(app: IraApp, talkRequests: Int) {
    var paired by remember { mutableStateOf(app.paired) }
    var screen by remember { mutableStateOf(Screen.Talk) }
    Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Column(Modifier.safeDrawingPadding()) {
            if (!paired) {
                PairScreen(app) {
                    paired = true
                    screen = Screen.Talk
                }
                return@Column
            }
            BackHandler(enabled = screen != Screen.Talk) { screen = Screen.Talk }
            when (screen) {
                Screen.Talk -> TalkScreen(app, talkRequests, onSkills = { screen = Screen.Skills }, onSettings = { screen = Screen.Settings })
                Screen.Skills -> SkillsScreen(app, onBack = { screen = Screen.Talk })
                Screen.Settings ->
                    SettingsScreen(app, onBack = { screen = Screen.Talk }, onUnpaired = {
                        paired = false
                        screen = Screen.Talk
                    })
            }
        }
    }
}

@Composable
fun TopRow(title: String, onBack: (() -> Unit)? = null, actions: @Composable () -> Unit = {}) {
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (onBack != null) TextButton(onClick = onBack) { Text("Back") }
        Text(
            title,
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(horizontal = 8.dp).weight(1f),
        )
        actions()
    }
}

@Composable
fun PairScreen(app: IraApp, onPaired: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var entry by remember { mutableStateOf("") }
    var server by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val typedCode = Regex("^[A-Za-z0-9-]{8,20}$").matches(entry.trim())

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Spacer(Modifier.height(24.dp))
        Text("Pair this phone with your Ira", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
        Text(
            "On your Ira, open Your devices, add a device, choose Android phone and the skills it may use, " +
                "and enter your PIN. Then paste the pairing link here, or type the 8-character code " +
                "and your Ira's address. A code works once, for 10 minutes.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        OutlinedTextField(
            value = entry,
            onValueChange = {
                entry = it
                error = null
            },
            label = { Text("Pairing link or code") },
            placeholder = { Text("https://ira.example.com/pair#code=ABCD-EFGH") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedButton(onClick = {
            val clip = context.getSystemService(ClipboardManager::class.java).primaryClip
            clip?.getItemAt(0)?.coerceToText(context)?.toString()?.trim()?.let {
                entry = it
                error = null
            }
        }) { Text("Paste") }
        if (typedCode) {
            OutlinedTextField(
                value = server,
                onValueChange = {
                    server = it
                    error = null
                },
                label = { Text("Your Ira's address") },
                placeholder = { Text("https://ira.example.com") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        Button(
            enabled = !busy && entry.isNotBlank(),
            onClick = {
                busy = true
                error = null
                scope.launch {
                    try {
                        val paired =
                            withContext(Dispatchers.IO) {
                                val (base, code) = Pairing.parse(entry, server.ifBlank { null })
                                Pairing.exchange(base, code, BuildConfig.VERSION_NAME, Net.post)
                            }
                        app.savePairing(paired)
                        onPaired()
                    } catch (exc: PairError) {
                        error = Plain.sentence(exc.message)
                    } catch (_: Exception) {
                        error = "That did not work. Check the address and the code, then try again."
                    } finally {
                        busy = false
                    }
                }
            },
            modifier = Modifier.fillMaxWidth().height(52.dp),
        ) {
            if (busy) CircularProgressIndicator(Modifier.height(20.dp), strokeWidth = 2.dp) else Text("Pair")
        }
        Text(
            "The phone keeps its own key in Android's Keystore. Removing the phone on your Ira stops the key at once.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
fun SettingsScreen(app: IraApp, onBack: () -> Unit, onUnpaired: () -> Unit) {
    val context = LocalContext.current
    val link by app.deviceStatus.collectAsState()
    var confirm by remember { mutableStateOf(false) }
    var removing by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize()) {
        TopRow("Settings", onBack)
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Fact("Your Ira", app.settings.server ?: "")
            Fact("This phone", app.settings.label)
            Fact("Connection for the phone's tools", linkText(link))
            Fact("App", "${BuildConfig.VERSION_NAME} (${if (app.tools.flavor.name == "PLAY") "Google Play build" else "personal build"})")
            HorizontalDivider()
            TextButton(onClick = { app.settings.checklistHidden = false; onBack() }) { Text("Show the setup checklist") }
            TextButton(onClick = { openAppSettings(context) }) { Text("Android's settings for Ira (permissions, notifications)") }
            TextButton(onClick = { open(context, PRIVACY_URL) }) { Text("Privacy policy") }
            TextButton(onClick = { open(context, "https://github.com/helloupendra/ira") }) { Text("Source code (MIT licence)") }
            HorizontalDivider()
            OutlinedButton(onClick = { confirm = true }, enabled = !removing) { Text(if (removing) "Removing..." else "Remove this phone from Ira") }
            Text(
                "Removing the phone stops its key on your Ira at once and forgets it here. To use Ira again, pair the phone again.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
    if (confirm) {
        AlertDialog(
            onDismissRequest = { confirm = false },
            title = { Text("Remove this phone?") },
            text = { Text("Ira will stop using this phone's tools, and its key stops working.") },
            confirmButton = {
                TextButton(onClick = {
                    confirm = false
                    removing = true
                    app.unpair { onUnpaired() }
                }) { Text("Remove") }
            },
            dismissButton = { TextButton(onClick = { confirm = false }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun Fact(label: String, value: String) {
    Column {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.bodyLarge)
    }
}

fun linkText(state: LinkState): String =
    when (state) {
        LinkState.Off -> "Off (on while Ira is open or a call is on)"
        LinkState.Connecting -> "Connecting"
        is LinkState.Connected -> "Connected"
        is LinkState.Waiting -> "Trying again in ${state.seconds} s"
        LinkState.Refused -> "Refused: this phone was removed. Pair it again."
    }

fun open(context: Context, url: String) {
    try {
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    } catch (_: Exception) {
    }
}

@Composable
fun OnStart(key: Any?, block: () -> Unit) {
    LaunchedEffect(key) { block() }
}
