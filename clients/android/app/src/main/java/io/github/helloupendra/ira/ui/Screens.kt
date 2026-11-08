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
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
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
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.helloupendra.ira.BuildConfig
import io.github.helloupendra.ira.IraApp
import io.github.helloupendra.ira.core.Approvals
import io.github.helloupendra.ira.core.Flavor
import io.github.helloupendra.ira.core.PairError
import io.github.helloupendra.ira.core.Pairing
import io.github.helloupendra.ira.core.Plain
import io.github.helloupendra.ira.core.ThemeChoice
import io.github.helloupendra.ira.device.LinkState
import io.github.helloupendra.ira.net.Net
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class Screen { Talk, Skills, Settings, Approvals, Drop }

/** The privacy policy: the project's own privacy page. */
const val PRIVACY_URL = "https://helloupendra.github.io/ira/docs/privacy/"

@Composable
fun IraScreens(app: IraApp, talkRequest: Long, dropRequests: Int = 0) {
    // Taken once: coming back to Talk from Settings must not start the microphone again.
    var talkTaken by rememberSaveable { mutableLongStateOf(0L) }
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
                    TalkScreen(app, if (talkRequest > talkTaken) talkRequest else 0L, onTalkTaken = { talkTaken = it }, onSkills = { screen = Screen.Skills }, onSettings = { screen = Screen.Settings }, onDrop = { screen = Screen.Drop })
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
fun PairScreen(app: IraApp, onPaired: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var entry by remember { mutableStateOf("") }
    var server by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val typedCode = Regex("^[A-Za-z0-9-]{8,20}$").matches(entry.trim())

    val colors = Presence.colors
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Spacer(Modifier.height(16.dp))
        Lens(56.dp)
        Text("Pair this phone with your Ira", fontSize = 26.sp, lineHeight = 32.sp, fontWeight = FontWeight.SemiBold, color = colors.ink)
        Text(
            "On your Ira, open Your devices, add a device, choose Android phone and the skills it may use, " +
                "and enter your PIN. Then paste the pairing link here, or type the 8-character code " +
                "and your Ira's address. A code works once, for 10 minutes.",
            fontSize = 14.sp,
            lineHeight = 20.sp,
            color = colors.muted,
        )
        Column(Modifier.fillMaxWidth().presenceCard(colors, radius = 16.dp).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
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
            PillButton("Paste", {
                val clip = context.getSystemService(ClipboardManager::class.java).primaryClip
                clip?.getItemAt(0)?.coerceToText(context)?.toString()?.trim()?.let {
                    entry = it
                    error = null
                }
            }, compact = true)
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
            error?.let { Text(it, color = colors.down, fontSize = 14.sp) }
        }
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
            fontSize = 12.sp,
            lineHeight = 17.sp,
            color = colors.muted,
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
    val theme by app.theme.collectAsState()
    Column(Modifier.fillMaxSize()) {
        ScreenHeader("Settings", onBack)
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(24.dp),
        ) {
            Section("Appearance", note = "System follows the light or dark setting of your phone.") {
                SegmentedPill(
                    options = ThemeChoice.entries.map { it.label },
                    selected = ThemeChoice.entries.indexOf(theme),
                    onSelect = { app.chooseTheme(ThemeChoice.entries[it]) },
                    modifier = Modifier.fillMaxWidth().padding(12.dp),
                )
            }
            Section("This phone") {
                ItemRow("Your Ira", server)
                switched?.let {
                    Text(it, color = Presence.colors.green, fontSize = 13.sp, modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 12.dp))
                }
                Hairline()
                ItemRow("This phone", app.settings.label)
                Hairline()
                ItemRow("Connection for the phone's tools", linkText(link))
                Hairline()
                ItemRow(
                    "App",
                    BuildConfig.VERSION_NAME + " (" +
                        when (app.tools.flavor) {
                            Flavor.PLAY -> "Google Play build"
                            Flavor.PLAY_LITE -> "Google Play build, without call history and SMS"
                            Flavor.PERSONAL -> "personal build"
                        } + ")",
                )
            }
            Section("Ira and Android") {
                if (Approvals.WINDOW) {
                    ItemRow("Approvals", "Fewer PINs for one task", onClick = onApprovals) { Chevron() }
                    Hairline()
                }
                ItemRow("Show the setup checklist", onClick = { app.settings.checklistHidden = false; onBack() }) { Chevron() }
                Hairline()
                ItemRow("Android's settings for Ira", "Permissions, notifications", onClick = { openAppSettings(context) }) { Chevron() }
            }
            Section("Your data") {
                ItemRow("Export or delete your data", "On your Ira, Your data", onClick = { open(context, app.settings.server.orEmpty()) }) { Chevron() }
                Hairline()
                ItemRow("Privacy policy", onClick = { open(context, PRIVACY_URL) }) { Chevron() }
                Hairline()
                ItemRow("Source code", "MIT licence", onClick = { open(context, "https://github.com/helloupendra/ira") }) { Chevron() }
            }
            Section("Pairing") {
                ItemRow(
                    "Pair with another Ira…",
                    "Move this phone to another Ira server. It stays paired with this one until the new pairing works.",
                    onClick = if (removing) null else ({ another = true }),
                ) { Chevron() }
                Hairline()
                ItemRow(
                    if (removing) "Removing..." else "Remove this phone from Ira",
                    "Removing the phone stops its key on your Ira at once and forgets it here. To use Ira again, pair the phone again.",
                    onClick = if (removing) null else ({ confirm = true }),
                    titleColor = Presence.colors.down,
                )
            }
            Spacer(Modifier.height(8.dp))
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
