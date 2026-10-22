package io.github.helloupendra.ira.core

/**
 * The first-run checklist: what is left before Ira can do everything this phone offers,
 * each step with one thing to tap. Plain facts in, steps out, so it is tested on the JVM.
 */
object Checklist {
    enum class Action { ALLOW_MICROPHONE, ALLOW_NOTIFICATIONS, OPEN_ASSISTANT_SETTINGS, OPEN_YOUR_IRA, OPEN_SKILLS }

    data class Facts(
        val microphone: Boolean,
        /** Null when Android needs no notification permission (before Android 13). */
        val notifications: Boolean?,
        val assistant: Boolean,
        /** Skills switched on for this phone on the person's Ira. */
        val skillsOnServer: Set<String>,
        /** Of those, the ones the phone still has to allow (a permission or a setting). */
        val skillsWaitingOnPhone: Set<String>,
    )

    data class Step(val title: String, val detail: String, val done: Boolean, val action: Action, val button: String)

    fun steps(facts: Facts): List<Step> =
        buildList {
            add(
                Step(
                    "Let Ira hear you",
                    "The microphone is used only during a call you start, and nothing is recorded.",
                    facts.microphone,
                    Action.ALLOW_MICROPHONE,
                    "Allow",
                ),
            )
            if (facts.notifications != null) {
                add(
                    Step(
                        "Let Ira show notifications",
                        "For the call in progress, your reminders, and news from Ira.",
                        facts.notifications,
                        Action.ALLOW_NOTIFICATIONS,
                        "Allow",
                    ),
                )
            }
            add(
                Step(
                    "Make Ira your digital assistant",
                    "Then a long press of the power button opens Ira, ready to listen.",
                    facts.assistant,
                    Action.OPEN_ASSISTANT_SETTINGS,
                    "Open settings",
                ),
            )
            add(
                Step(
                    "Choose what Ira may do on this phone",
                    "On your Ira, open Your devices and switch on skills for this phone, such as Calls and Contacts. Each needs your PIN.",
                    facts.skillsOnServer.isNotEmpty(),
                    Action.OPEN_YOUR_IRA,
                    "Open your Ira",
                ),
            )
            add(
                Step(
                    "Allow those skills on the phone",
                    if (facts.skillsWaitingOnPhone.isEmpty()) {
                        "Android allows everything you switched on."
                    } else {
                        "Android still has to allow: ${facts.skillsWaitingOnPhone.sorted().joinToString(", ")}."
                    },
                    facts.skillsOnServer.isNotEmpty() && facts.skillsWaitingOnPhone.isEmpty(),
                    Action.OPEN_SKILLS,
                    "Open Skills",
                ),
            )
        }

    fun complete(facts: Facts): Boolean = steps(facts).all { it.done }
}

/** Server and library messages as sentences a person can act on. */
object Plain {
    fun sentence(message: String?): String {
        val text = message?.trim().orEmpty().ifEmpty { "Something went wrong." }
        val reached = Regex("^could not reach (\\S+): (.*)$").matchEntire(text)
        if (reached != null) {
            return "Couldn't reach ${reached.groupValues[1]} (${reached.groupValues[2]}). Check the address, and that the phone is online."
        }
        val first = text.replaceFirstChar { it.uppercase() }
        return if (first.endsWith(".") || first.endsWith("?") || first.endsWith("!")) first else "$first."
    }
}
