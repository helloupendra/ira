package io.github.helloupendra.ira.tools

import android.app.AutomaticZenRule
import android.app.NotificationManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.service.notification.Condition
import io.github.helloupendra.ira.core.Args
import io.github.helloupendra.ira.core.ToolFailure
import io.github.helloupendra.ira.ui.MainActivity
import kotlinx.serialization.json.JsonElement

/**
 * Settings an app may change. Android lets no app switch Wi-Fi, Bluetooth, mobile data or
 * NFC on its own; for those the phone shows the system's own switch for a tap.
 */
class SettingsTools(private val context: Context) {
    fun toggle(args: Args): JsonElement {
        val setting =
            args.choice("setting", listOf("flashlight", "ringer", "volume", "dnd", "wifi", "bluetooth", "mobile_data", "nfc"))
                ?: throw ToolFailure("say which setting")
        val value = args.string("value", 10)?.lowercase()
        return when (setting) {
            "flashlight" -> flashlight(onOff(value))
            "ringer" -> ringer(value ?: throw ToolFailure("say normal, vibrate or silent"))
            "volume" -> volume(value?.toIntOrNull() ?: throw ToolFailure("say a volume from 0 to 100"))
            "dnd" -> doNotDisturb(onOff(value))
            "wifi" -> panel(Settings.Panel.ACTION_WIFI, "Wi-Fi")
            "bluetooth" -> panel(Settings.ACTION_BLUETOOTH_SETTINGS, "Bluetooth")
            "mobile_data" -> panel(Settings.Panel.ACTION_INTERNET_CONNECTIVITY, "mobile data")
            else -> panel(Settings.Panel.ACTION_NFC, "NFC")
        }
    }

    private fun onOff(value: String?): Boolean =
        when (value) {
            "on", "true", "yes", "1" -> true
            "off", "false", "no", "0" -> false
            else -> throw ToolFailure("say on or off")
        }

    private fun flashlight(on: Boolean): JsonElement {
        val cameras = context.getSystemService(CameraManager::class.java)
        val id =
            cameras.cameraIdList.firstOrNull { cameras.getCameraCharacteristics(it).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true }
                ?: throw ToolFailure("this phone has no flashlight")
        cameras.setTorchMode(id, on)
        return Results.of("flashlight" to on, "summary" to "Flashlight ${if (on) "on" else "off"}.")
    }

    private fun ringer(value: String): JsonElement {
        val audio = context.getSystemService(AudioManager::class.java)
        val mode =
            when (value) {
                "normal", "on" -> AudioManager.RINGER_MODE_NORMAL
                "vibrate" -> AudioManager.RINGER_MODE_VIBRATE
                "silent", "off" -> AudioManager.RINGER_MODE_SILENT
                else -> throw ToolFailure("say normal, vibrate or silent")
            }
        try {
            audio.ringerMode = mode
        } catch (_: SecurityException) {
            throw ToolFailure("silent needs Do Not Disturb access for Ira: open Ira, Skills, Settings")
        }
        return Results.of("ringer" to value, "summary" to "Ringer: $value.")
    }

    private fun volume(percent: Int): JsonElement {
        if (percent !in 0..100) throw ToolFailure("say a volume from 0 to 100")
        val audio = context.getSystemService(AudioManager::class.java)
        val max = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        audio.setStreamVolume(AudioManager.STREAM_MUSIC, Math.round(percent / 100f * max), AudioManager.FLAG_SHOW_UI)
        return Results.of("volume" to percent, "summary" to "Media volume $percent%.")
    }

    private fun doNotDisturb(on: Boolean): JsonElement {
        val nm = context.getSystemService(NotificationManager::class.java)
        if (!nm.isNotificationPolicyAccessGranted) {
            Launcher.start(context, Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS), "allow Ira to switch Do Not Disturb")
            throw ToolFailure("Ira needs Do Not Disturb access first; the phone shows where to allow it")
        }
        if (Build.VERSION.SDK_INT >= 35) {
            // Apps for Android 15 and later switch Do Not Disturb through a rule of their own.
            val id = rule(nm)
            val state = if (on) Condition.STATE_TRUE else Condition.STATE_FALSE
            nm.setAutomaticZenRuleState(id, Condition(RULE_URI, "Switched by Ira", state))
        } else {
            nm.setInterruptionFilter(if (on) NotificationManager.INTERRUPTION_FILTER_PRIORITY else NotificationManager.INTERRUPTION_FILTER_ALL)
        }
        return Results.of("dnd" to on, "summary" to "Do Not Disturb ${if (on) "on" else "off"}.")
    }

    private fun rule(nm: NotificationManager): String {
        nm.automaticZenRules.entries.firstOrNull { it.value.conditionId == RULE_URI }?.let { return it.key }
        val rule =
            AutomaticZenRule.Builder("Ira", RULE_URI)
                .setConfigurationActivity(ComponentName(context, MainActivity::class.java))
                .setInterruptionFilter(NotificationManager.INTERRUPTION_FILTER_PRIORITY)
                .setManualInvocationAllowed(true)
                .build()
        return nm.addAutomaticZenRule(rule) ?: throw ToolFailure("the phone did not allow a Do Not Disturb rule")
    }

    private fun panel(action: String, what: String): JsonElement {
        val started = Launcher.start(context, Intent(action), "switch $what")
        return Results.of(
            "opened" to started,
            "summary" to
                if (started) {
                    "Android lets no app switch $what; its switch is on the screen for you to tap."
                } else {
                    "Android lets no app switch $what; the phone shows a notification that opens its switch."
                },
        )
    }

    private companion object {
        val RULE_URI: Uri = Uri.parse("condition://io.github.helloupendra.ira/dnd")
    }
}
