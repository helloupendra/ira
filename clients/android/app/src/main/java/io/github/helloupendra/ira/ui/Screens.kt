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
import androidx.compose.ui.semantics.Role
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.Checkbox
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
import io.github.helloupendra.ira.core.Approvals
import io.github.helloupendra.ira.core.Flavor
import io.github.helloupendra.ira.core.PairError
import io.github.helloupendra.ira.core.Pairing
import io.github.helloupendra.ira.core.Plain
import io.github.helloupendra.ira.device.LinkState
import io.github.helloupendra.ira.net.Net
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class Screen { Talk, Skills, Settings, Approvals, Drop }

/** The privacy policy: the project's own privacy page. */
const val PRIVACY_URL = "https://helloupendra.github.io/ira/docs/privacy/"

@Composable
fun IraScreens(app: IraApp, talkRequests: Int, dropRequests: Int = 0) {
    var paired by remember { mutableStateOf(app.paired) }
    var screen by remember { mutableStateOf(Screen.Talk) }
    LaunchedEffect(dropRequests) { if (dropRequests > 0 && paired) screen = Screen.Drop }
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
                Screen.Talk ->
                    TalkScreen(app, talkRequests, onSkills = { screen = Screen.Skills }, onSettings = { screen = Screen.Settings }, onDrop = { screen = Screen.Drop })
                Screen.Skills -> SkillsScreen(app, onBack = { screen = Screen.Talk })
                Screen.Settings ->
                    SettingsScreen(app, onBack = { screen = Screen.Talk }, onApprovals = { screen = Screen.Approvals }, onUnpaired = {
                        paired = false
                        screen = Screen.Talk
                    })
                Screen.Approvals -> ApprovalsScreen(app, onBack = { screen = Screen.Settings })
                Screen.Drop -> DropScreen(app, onBack = { screen = Screen.Talk })
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
fun SettingsScreen(app: IraApp, onBack: () -> Unit, onApprovals: () -> Unit, onUnpaired: () -> Unit) {
    val context = LocalContext.current
    val link by app.deviceStatus.collectAsState()
    var confirm by remember { mutableStateOf(false) }
    var removing by remember { mutableStateOf(false) }
    var another by remember { mutableStateOf(false) }
    var server by remember { mutableStateOf(app.settings.server.orEmpty()) }
    var switched by remember { mutableStateOf<String?>(null) }
    Column(Modifier.fillMaxSize()) {
        TopRow("Settings", onBack)
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Fact("Your Ira", server)
            switched?.let { Text(it, color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.bodyMedium) }
            Fact("This phone", app.settings.label)
            Fact("Connection for the phone's tools", linkText(link))
            Fact(
                "App",
                BuildConfig.VERSION_NAME + " (" +
                    when (app.tools.flavor) {
                        Flavor.PLAY -> "Google Play build"
                        Flavor.PLAY_LITE -> "Google Play build, without call history and SMS"
                        Flavor.PERSONAL -> "personal build"
                    } + ")",
            )
            HorizontalDivider()
            if (Approvals.WINDOW) TextButton(onClick = onApprovals) { Text("Approvals: fewer PINs for one task") }
            TextButton(onClick = { app.settings.checklistHidden = false; onBack() }) { Text("Show the setup checklist") }
            TextButton(onClick = { openAppSettings(context) }) { Text("Android's settings for Ira (permissions, notifications)") }
            TextButton(onClick = { open(context, app.settings.server.orEmpty()) }) { Text("Export or delete your data (on your Ira, Your data)") }
            TextButton(onClick = { open(context, PRIVACY_URL) }) { Text("Privacy policy") }
            TextButton(onClick = { open(context, "https://github.com/helloupendra/ira") }) { Text("Source code (MIT licence)") }
            HorizontalDivider()
            OutlinedButton(onClick = { another = true }, enabled = !removing) { Text("Pair with another Ira…") }
            Text(
                "Move this phone to another Ira server. It stays paired with this one until the new pairing works.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            OutlinedButton(onClick = { confirm = true }, enabled = !removing) { Text(if (removing) "Removing..." else "Remove this phone from Ira") }
            Text(
                "Removing the phone stops its key on your Ira at once and forgets it here. To use Ira again, pair the phone again.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
    if (another) {
        PairAnotherDialog(
            app = app,
            onPaired = { paired, forgot ->
                another = false
                server = paired
                switched = "Paired with $paired." + if (forgot) " The old Ira was told to forget this phone." else " The old Ira still lists this phone; remove it there if you like."
            },
            onClose = { another = false },
        )
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

/**
 * Pair with another Ira (Ira for Mac does the same): this pairing stays until the new one
 * works, and the old Ira is told to forget the phone only when the box is ticked.
 */
@Composable
private fun PairAnotherDialog(app: IraApp, onPaired: (server: String, forgotOld: Boolean) -> Unit, onClose: () -> Unit) {
    val context = LocalContext.current
    var entry by remember { mutableStateOf("") }
    var typedServer by remember { mutableStateOf("") }
    var removeOld by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val oldHost = app.settings.server.orEmpty().removePrefix("https://").removePrefix("http://")
    val typedCode = Regex("^[A-Za-z0-9-]{8,20}$").matches(entry.trim())
    AlertDialog(
        onDismissRequest = { if (!busy) onClose() },
        title = { Text("Pair with another Ira") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    "On the other Ira, open Your devices, add an Android phone, and copy its pairing link. " +
                        "This phone stays paired with $oldHost until the new pairing works.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                OutlinedTextField(
                    value = entry,
                    onValueChange = {
                        entry = it
                        error = null
                    },
                    label = { Text("Pairing link or code") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                TextButton(onClick = {
                    context.getSystemService(ClipboardManager::class.java).primaryClip?.getItemAt(0)?.coerceToText(context)?.toString()?.trim()?.let {
                        entry = it
                        error = null
                    }
                }) { Text("Paste") }
                if (typedCode) {
                    OutlinedTextField(
                        value = typedServer,
                        onValueChange = {
                            typedServer = it
                            error = null
                        },
                        label = { Text("The other Ira's address") },
                        placeholder = { Text("https://ira.example.com") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth().toggleable(value = removeOld, onValueChange = { removeOld = it }, role = Role.Checkbox)) {
                    Checkbox(checked = removeOld, onCheckedChange = null)
                    Text("Also remove this phone from $oldHost", modifier = Modifier.padding(start = 8.dp), style = MaterialTheme.typography.bodyMedium)
                }
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = {
            TextButton(
                enabled = entry.isNotBlank() && !busy,
                onClick = {
                    busy = true
                    error = null
                    val ticked = removeOld
                    app.pairAnother(entry, typedServer, ticked) { problem ->
                        busy = false
                        if (problem == null) onPaired(app.settings.server.orEmpty(), ticked) else error = problem
                    }
                },
            ) { Text(if (busy) "Pairing..." else "Pair") }
        },
        dismissButton = { TextButton(onClick = onClose, enabled = !busy) { Text("Cancel") } },
    )
}
