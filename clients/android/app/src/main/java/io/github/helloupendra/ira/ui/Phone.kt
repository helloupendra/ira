package io.github.helloupendra.ira.ui

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import io.github.helloupendra.ira.IraApp
import io.github.helloupendra.ira.core.Flavor
import io.github.helloupendra.ira.core.Permissions
import io.github.helloupendra.ira.core.SpecialAccess
import io.github.helloupendra.ira.core.ToolGate

/** The SMS and call-log permissions: on Google Play, asked for only once Ira is the assistant. */
val RESTRICTED = setOf(Permissions.READ_CALL_LOG, Permissions.READ_SMS, Permissions.SEND_SMS)

/** The permissions a skill still needs on this phone (that may be asked for now). */
fun missingPermissions(app: IraApp, state: ToolGate.State, skill: String): List<String> =
    app.tools.tools.filter { it.skill == skill }
        .flatMap { it.permissions + it.optionalPermissions }
        .distinct()
        .filter { app.tools.flavor == Flavor.PERSONAL || it !in RESTRICTED || state.assistantRole }
        .filter { it !in state.granted }

/** The settings switches a skill still needs. */
fun missingSpecial(app: IraApp, state: ToolGate.State, skill: String): List<SpecialAccess> =
    app.tools.tools.filter { it.skill == skill }.flatMap { it.special }.distinct().filter { it !in state.special }

/** Skills switched on for this phone on the person's Ira that the phone does not allow yet. */
fun skillsWaitingOnPhone(app: IraApp, state: ToolGate.State, on: Set<String>): Set<String> {
    val offered = app.tools.tools.map { it.skill }.toSet()
    return on.filter { it in offered }.filter { skill ->
        val required = app.tools.tools.filter { it.skill == skill }.flatMap { it.permissions }.toSet()
        val roleNeeded = app.tools.flavor == Flavor.PLAY && app.tools.tools.any { it.skill == skill && it.restricted } && !state.assistantRole
        roleNeeded || required.any { it !in state.granted } || missingSpecial(app, state, skill).isNotEmpty()
    }.toSet()
}

private fun start(context: Context, vararg intents: Intent) {
    for (intent in intents) {
        try {
            context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            return
        } catch (_: Exception) {
        }
    }
}

/** Android's page for this app: permissions, notifications, battery. */
fun openAppSettings(context: Context) =
    start(context, Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}")), Intent(Settings.ACTION_SETTINGS))

fun openNotificationSettings(context: Context) =
    start(
        context,
        Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName),
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}")),
    )

/** Settings, Apps, Default apps, Digital assistant app (or the nearest page this phone has). */
fun openAssistantSettings(context: Context) =
    start(context, Intent(Settings.ACTION_VOICE_INPUT_SETTINGS), Intent(Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS), Intent(Settings.ACTION_SETTINGS))

fun openSpecial(context: Context, access: SpecialAccess) {
    when (access) {
        SpecialAccess.NOTIFICATION_LISTENER -> start(context, Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        SpecialAccess.ACCESSIBILITY -> start(context, Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        SpecialAccess.EXACT_ALARMS ->
            if (Build.VERSION.SDK_INT >= 31) {
                start(context, Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:${context.packageName}")))
            }
        SpecialAccess.DO_NOT_DISTURB -> start(context, Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS))
    }
}

/** What a special access is for, in plain words, shown before Android's settings open. */
fun specialWhy(access: SpecialAccess): String =
    when (access) {
        SpecialAccess.NOTIFICATION_LISTENER -> "Android's Notification access page opens. Find Ira and switch it on."
        SpecialAccess.ACCESSIBILITY -> "Android's Accessibility page opens. Find Ira under Downloaded apps and switch it on."
        SpecialAccess.EXACT_ALARMS -> "Android's Alarms and reminders page opens. Switch it on for Ira so reminders come on time."
        SpecialAccess.DO_NOT_DISTURB -> "Android's Do Not Disturb access page opens. Switch it on for Ira."
    }
