package io.github.helloupendra.ira.ui

import io.github.helloupendra.ira.core.Skills

/**
 * The in-app disclosures Google Play asks for: each says what is read, why, and where it
 * goes, and is shown right before Android's own permission prompt, with Agree and Not now.
 */
object Disclosures {
    const val MIC_TITLE = "Ira listens only while you talk"

    fun mic(server: String): String =
        "To hear you, Ira uses the microphone while you talk to it. In a live call, the phone " +
            "notices when you speak and sends only what you say to your own Ira server ($server), " +
            "which turns it into text. When your Ira has no live calls, the phone's own speech " +
            "recognition (Google's on most phones) turns it into text instead: on the phone when " +
            "it can, otherwise online; your Ira then gets only the text. Nothing is recorded or " +
            "kept as audio. The microphone is on only while you talk: End, or two quiet minutes, " +
            "turn it off."

    fun skillTitle(skill: String): String =
        when (skill) {
            Skills.CALLS -> "Your calls"
            Skills.CONTACTS -> "Your contacts"
            Skills.MESSAGES -> "Your SMS"
            Skills.NOTIFICATIONS -> "Your notifications"
            Skills.REMINDERS -> "Reminders"
            Skills.CALENDAR -> "Your calendar"
            Skills.LOCATION -> "Your location"
            Skills.SCREEN -> "Your screen"
            else -> skill.replaceFirstChar { it.uppercase() }
        }

    /** The disclosure for a skill's data, or null when it reads nothing personal. */
    fun skill(skill: String, server: String): String? =
        when (skill) {
            Skills.CALLS ->
                "Ira reads your call log (who called or was called, their numbers, when, and how " +
                    "long) only when you ask, for example \"who called?\". What it reads is sent to " +
                    "your Ira server ($server), into your conversation, so Ira can answer. Ira also " +
                    "starts a call you ask for, after reading the name and number back and hearing " +
                    "your yes."
            Skills.CONTACTS ->
                "Ira looks up names and numbers in your contacts when you ask, to say whose number " +
                    "it is or to find a number to call or text. What it finds is sent to your Ira " +
                    "server ($server), into your conversation."
            Skills.MESSAGES ->
                "Ira reads your SMS when you ask, and sends an SMS you dictate after reading the " +
                    "number and the words back and hearing your yes. The messages it reads are sent " +
                    "to your Ira server ($server), into your conversation."
            Skills.NOTIFICATIONS ->
                "With notification access, Ira reads the notifications showing on your phone " +
                    "(WhatsApp, Telegram, email and other apps) when you ask, and answers a message " +
                    "through its own reply button after your yes. What it reads is sent to your Ira " +
                    "server ($server), into your conversation. The phone keeps no copy."
            Skills.REMINDERS ->
                "Ira sets alarms and timers in your clock app and shows reminders as notifications. " +
                    "A reminder's words stay on the phone until it goes off."
            Skills.CALENDAR ->
                "Ira reads the calendars on your phone when you ask, and adds an event after your " +
                    "yes. What it reads is sent to your Ira server ($server), into your conversation."
            Skills.LOCATION ->
                "Ira reads where the phone is, once, when you ask \"where am I?\", and only while " +
                    "Ira is on the screen. The place is sent to your Ira server ($server), into your " +
                    "conversation. The phone keeps no location history."
            Skills.SCREEN -> SCREEN_WARNING
            else -> null
        }

    const val SCREEN_WARNING =
        "This lets Ira read whatever is on your screen and tap and type for you, like a person " +
            "holding your phone. It can see private things: messages, bank apps, anything on the " +
            "screen. It reads nothing on its own and never touches password fields, and every use " +
            "needs your PIN on your Ira server. Switch it on only if you trust your Ira server and " +
            "everyone who can talk to it. You can switch it off in Android's Accessibility settings " +
            "at any time."
}
