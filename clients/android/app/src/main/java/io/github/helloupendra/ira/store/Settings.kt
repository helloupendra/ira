package io.github.helloupendra.ira.store

import android.content.Context
import io.github.helloupendra.ira.core.Paired

/** What the app remembers besides the token: none of it is secret, none of it is content. */
class Settings(context: Context) {
    private val prefs = context.getSharedPreferences("ira_settings", Context.MODE_PRIVATE)

    val server: String?
        get() = prefs.getString("server", null)

    val deviceId: Int
        get() = prefs.getInt("device_id", 0)

    val label: String
        get() = prefs.getString("label", null) ?: "My Android phone"

    val assistant: String
        get() = prefs.getString("assistant", null) ?: "Ira"

    val websocketPath: String
        get() = prefs.getString("websocket", null) ?: "/v1/devices/ws"

    /** The person agreed to the microphone disclosure (Google Play's prominent disclosure). */
    var micDisclosureAccepted: Boolean
        get() = prefs.getBoolean("mic_disclosure", false)
        set(value) = prefs.edit().putBoolean("mic_disclosure", value).apply()

    /** The person read what the phone skills do with their data, before any were asked for. */
    var skillsDisclosureAccepted: Boolean
        get() = prefs.getBoolean("skills_disclosure", false)
        set(value) = prefs.edit().putBoolean("skills_disclosure", value).apply()

    /** The person accepted the warning for the Accessibility fallback (personal build). */
    var screenWarningAccepted: Boolean
        get() = prefs.getBoolean("screen_warning", false)
        set(value) = prefs.edit().putBoolean("screen_warning", value).apply()

    /** The person hid the first-run checklist (Settings can show it again). */
    var checklistHidden: Boolean
        get() = prefs.getBoolean("checklist_hidden", false)
        set(value) = prefs.edit().putBoolean("checklist_hidden", value).apply()

    /** The live conversation to continue (an id the server gave, not its content). */
    var conversationId: String?
        get() = prefs.getString("conversation", null)
        set(value) = prefs.edit().putString("conversation", value).apply()

    /** Skills switched on for this phone, as the server last said. */
    var skillsOn: Set<String>
        get() = prefs.getStringSet("skills_on", emptySet()) ?: emptySet()
        set(value) = prefs.edit().putStringSet("skills_on", value).apply()

    val paired: Boolean
        get() = server != null && deviceId != 0

    fun savePairing(paired: Paired) {
        prefs.edit()
            .putString("server", paired.server)
            .putInt("device_id", paired.deviceId)
            .putString("label", paired.label)
            .putString("assistant", paired.assistant)
            .putString("websocket", paired.websocket)
            .putStringSet("skills_on", paired.skills.toSet())
            .remove("conversation")
            .apply()
    }

    fun forgetPairing() {
        prefs.edit()
            .remove("server")
            .remove("device_id")
            .remove("label")
            .remove("websocket")
            .remove("conversation")
            .remove("skills_on")
            .apply()
    }
}
