package io.github.helloupendra.ira.core

/**
 * Whether a tool may run now on this phone, and if not, what the person can do about it.
 * The answer goes back to Ira as the tool's error, so it is written for the person.
 */
object ToolGate {
    data class State(
        val flavor: Flavor,
        /** This app is the phone's default digital assistant. */
        val assistantRole: Boolean,
        /** A live call with Ira is on, in this app, on this phone. */
        val callOn: Boolean,
        val granted: Set<String>,
        val special: Set<SpecialAccess>,
    )

    fun check(spec: ToolSpec, state: State): String? {
        if (state.flavor !in spec.flavors) return "this build of the app does not have ${spec.name}"
        if (spec.restricted && state.flavor == Flavor.PLAY) {
            // Google Play allows SMS and call-log permissions only to the default assistant,
            // and this build uses them only while the person talks to Ira on the phone.
            if (!state.assistantRole) {
                return "make Ira the phone's digital assistant first (Settings, Apps, Default apps, " +
                    "Digital assistant app); calls and SMS need it"
            }
            if (!state.callOn) return "calls and SMS are read only while you talk to Ira on the phone"
        }
        val missing = spec.permissions.filter { it !in state.granted }
        if (missing.isNotEmpty()) {
            return "the phone has not allowed ${missing.joinToString(" and ") { label(it) }} yet: " +
                "open Ira on the phone, Skills, and allow it"
        }
        for (access in spec.special) {
            if (access !in state.special) return "${specialLabel(access)} is off: open Ira on the phone, Skills, and switch it on"
        }
        return null
    }

    fun label(permission: String): String =
        when (permission) {
            Permissions.READ_CALL_LOG -> "the call log"
            Permissions.READ_CONTACTS -> "contacts"
            Permissions.CALL_PHONE -> "phone calls"
            Permissions.READ_SMS -> "reading SMS"
            Permissions.SEND_SMS -> "sending SMS"
            Permissions.READ_CALENDAR -> "reading the calendar"
            Permissions.WRITE_CALENDAR -> "changing the calendar"
            Permissions.COARSE_LOCATION, Permissions.FINE_LOCATION -> "location"
            Permissions.POST_NOTIFICATIONS -> "notifications"
            Permissions.RECORD_AUDIO -> "the microphone"
            else -> permission.substringAfterLast('.').lowercase().replace('_', ' ')
        }

    fun specialLabel(access: SpecialAccess): String =
        when (access) {
            SpecialAccess.NOTIFICATION_LISTENER -> "Notification access"
            SpecialAccess.ACCESSIBILITY -> "Ira's Accessibility service"
            SpecialAccess.EXACT_ALARMS -> "Alarms and reminders"
            SpecialAccess.DO_NOT_DISTURB -> "Do Not Disturb access"
        }
}
