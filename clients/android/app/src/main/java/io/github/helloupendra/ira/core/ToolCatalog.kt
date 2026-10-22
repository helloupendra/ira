package io.github.helloupendra.ira.core

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/** Which build this is: what Google Play allows, or the sideloaded build with everything. */
enum class Flavor {
    PLAY,
    PERSONAL;

    companion object {
        fun of(name: String): Flavor = if (name.equals("personal", ignoreCase = true)) PERSONAL else PLAY
    }
}

/** Something a tool needs that the person grants in Android, outside a runtime prompt. */
enum class SpecialAccess {
    NOTIFICATION_LISTENER,
    ACCESSIBILITY,
    EXACT_ALARMS,
    DO_NOT_DISTURB,
}

/**
 * One tool the phone offers Ira: its name, what it does (the model reads this), the skill
 * the person switches on for it, its tier (0 reads, 1 small and undoable, 2 needs their
 * "yes", 3 needs their PIN), and its arguments as a JSON Schema object.
 */
data class ToolSpec(
    val name: String,
    val description: String,
    val skill: String,
    val tier: Int,
    val parameters: JsonObject,
    /** Runtime permissions the tool cannot work without. */
    val permissions: List<String> = emptyList(),
    /** Runtime permissions that make it better (names for numbers), asked for with the rest. */
    val optionalPermissions: List<String> = emptyList(),
    val special: List<SpecialAccess> = emptyList(),
    /**
     * Uses SMS or call-log permissions. On Google Play these are allowed only while the app
     * is the default digital assistant, and this app also keeps them to a call on the phone.
     */
    val restricted: Boolean = false,
    val flavors: Set<Flavor> = setOf(Flavor.PLAY, Flavor.PERSONAL),
) {
    fun toJson(): JsonObject =
        buildJsonObject {
            put("name", JsonPrimitive(name))
            put("description", JsonPrimitive(description))
            put("parameters", parameters)
            put("skill", JsonPrimitive(skill))
            put("tier", JsonPrimitive(tier))
        }
}

object Skills {
    const val CALLS = "calls"
    const val CONTACTS = "contacts"
    const val MESSAGES = "messages"
    const val NOTIFICATIONS = "notifications"
    const val REMINDERS = "reminders"
    const val CALENDAR = "calendar"
    const val APPS = "apps"
    const val MEDIA = "media"
    const val LOCATION = "location"
    const val SETTINGS = "settings"
    const val SCREEN = "screen"

    /** What each skill lets Ira do, in plain words, for the Skills screen. */
    val about: Map<String, String> =
        linkedMapOf(
            CALLS to "See your recent calls and start a call after your yes.",
            CONTACTS to "Look up names and numbers in your contacts.",
            MESSAGES to "Read your SMS and send one after your yes.",
            NOTIFICATIONS to "Read the notifications on your phone, and answer a message through its own reply button after your yes.",
            REMINDERS to "Set alarms, timers and reminders.",
            CALENDAR to "Read your calendar, and add an event after your yes.",
            APPS to "Open an app, or start directions in your maps app.",
            MEDIA to "Play, pause or skip what is playing, and change the volume.",
            LOCATION to "Say where the phone is, once, when you ask. Never stored.",
            SETTINGS to "Switch the flashlight, ringer, volume or Do Not Disturb.",
            SCREEN to "Read the screen and tap or type for you, like a person would. Each use needs your PIN.",
        )
}

object Permissions {
    const val READ_CALL_LOG = "android.permission.READ_CALL_LOG"
    const val READ_CONTACTS = "android.permission.READ_CONTACTS"
    const val CALL_PHONE = "android.permission.CALL_PHONE"
    const val READ_SMS = "android.permission.READ_SMS"
    const val SEND_SMS = "android.permission.SEND_SMS"
    const val READ_CALENDAR = "android.permission.READ_CALENDAR"
    const val WRITE_CALENDAR = "android.permission.WRITE_CALENDAR"
    const val COARSE_LOCATION = "android.permission.ACCESS_COARSE_LOCATION"
    const val FINE_LOCATION = "android.permission.ACCESS_FINE_LOCATION"
    const val POST_NOTIFICATIONS = "android.permission.POST_NOTIFICATIONS"
    const val RECORD_AUDIO = "android.permission.RECORD_AUDIO"
}

object ToolCatalog {
    fun forFlavor(flavor: Flavor): List<ToolSpec> = all(flavor).filter { flavor in it.flavors }

    fun names(flavor: Flavor): Set<String> = forFlavor(flavor).map { it.name }.toSet()

    private fun all(flavor: Flavor): List<ToolSpec> =
        listOf(
            ToolSpec(
                name = "calls_recent",
                description =
                    "Recent calls on this phone, newest first: the person's name (from the phone's contacts), " +
                        "the number, incoming, outgoing or missed, when, and how long. For 'who called?' or " +
                        "'kiska call aaya tha?'.",
                skill = Skills.CALLS,
                tier = 0,
                parameters =
                    params(
                        "limit" to integer("How many calls, newest first (default 10).", 1, 50),
                        "kind" to text("Only these calls.", enum = listOf("any", "missed", "incoming", "outgoing")),
                        "since_hours" to integer("Only calls in the last this many hours.", 1, 24 * 30),
                    ),
                permissions = listOf(Permissions.READ_CALL_LOG),
                optionalPermissions = listOf(Permissions.READ_CONTACTS),
                restricted = true,
            ),
            ToolSpec(
                name = "contacts_lookup",
                description =
                    "Find people in this phone's contacts by name or by phone number, with their numbers. " +
                        "Turns a number into a name, or a name into a number before a call or a message. " +
                        "Several matches mean asking which one.",
                skill = Skills.CONTACTS,
                tier = 0,
                parameters =
                    params(
                        "query" to text("A name, part of a name, or a phone number.", maxLength = 100),
                        "limit" to integer("How many people at most (default 5).", 1, 20),
                        required = listOf("query"),
                    ),
                permissions = listOf(Permissions.READ_CONTACTS),
            ),
            ToolSpec(
                name = "call_place",
                description =
                    "Start a phone call from this phone. Give the exact number and, when known, the " +
                        "person's name: both are read back before the call starts.",
                skill = Skills.CALLS,
                tier = 2,
                parameters =
                    params(
                        "number" to text("The phone number to call, as digits, with + and the country code if known.", maxLength = 24),
                        "name" to text("Who is being called, as the person knows them.", maxLength = 80),
                        required = listOf("number"),
                    ),
                permissions = listOf(Permissions.CALL_PHONE),
            ),
            ToolSpec(
                name = "sms_read",
                description =
                    "Read SMS text messages on this phone, newest first: from whom (name and number), " +
                        "when, and the text. Filter by a number or a name, or by words in the text.",
                skill = Skills.MESSAGES,
                tier = 0,
                parameters =
                    params(
                        "from" to text("Only messages from this number or contact name.", maxLength = 80),
                        "contains" to text("Only messages containing these words.", maxLength = 80),
                        "limit" to integer("How many messages, newest first (default 5).", 1, 20),
                        "since_hours" to integer("Only messages in the last this many hours.", 1, 24 * 30),
                    ),
                permissions = listOf(Permissions.READ_SMS),
                optionalPermissions = listOf(Permissions.READ_CONTACTS),
                restricted = true,
            ),
            ToolSpec(
                name = "sms_send",
                description =
                    "Send an SMS from this phone. Give the exact number, the person's name when known, " +
                        "and the exact text: all are read back before it is sent.",
                skill = Skills.MESSAGES,
                tier = 2,
                parameters =
                    params(
                        "number" to text("The phone number to send to.", maxLength = 24),
                        "name" to text("Who it is for, as the person knows them.", maxLength = 80),
                        "text" to text("The exact message.", maxLength = 1000),
                        required = listOf("number", "text"),
                    ),
                permissions = listOf(Permissions.SEND_SMS),
                restricted = true,
            ),
            ToolSpec(
                name = "notifications_read",
                description =
                    "Read the notifications showing on this phone now (WhatsApp, Telegram, email, " +
                        "deliveries and other apps): the app, the sender or title, the text and the time. " +
                        "Each has a key; can_reply says a message can be answered with notification_reply.",
                skill = Skills.NOTIFICATIONS,
                tier = 0,
                parameters =
                    params(
                        "app" to text("Only this app's notifications, by its name (for example WhatsApp).", maxLength = 60),
                        "limit" to integer("How many at most, newest first (default 10).", 1, 30),
                    ),
                special = listOf(SpecialAccess.NOTIFICATION_LISTENER),
            ),
            ToolSpec(
                name = "notification_reply",
                description =
                    "Answer a message notification on this phone (a WhatsApp or Telegram message, for " +
                        "example) through the notification's own reply button. Use its key from " +
                        "notifications_read, and give who it goes to and the exact text: both are read back " +
                        "before it is sent.",
                skill = Skills.NOTIFICATIONS,
                tier = 2,
                parameters =
                    params(
                        "key" to text("The notification's key, from notifications_read.", maxLength = 300),
                        "to" to text("Who or which chat the reply goes to, as the notification shows it.", maxLength = 80),
                        "app" to text("The app, as the notification shows it.", maxLength = 60),
                        "text" to text("The exact reply.", maxLength = 1000),
                        required = listOf("key", "text"),
                    ),
                special = listOf(SpecialAccess.NOTIFICATION_LISTENER),
            ),
            ToolSpec(
                name = "alarm_set",
                description =
                    "Set an alarm in this phone's clock app at a time of day (24-hour), optionally " +
                        "repeating on some days of the week.",
                skill = Skills.REMINDERS,
                tier = 1,
                parameters =
                    params(
                        "hour" to integer("The hour, 0 to 23.", 0, 23),
                        "minute" to integer("The minute, 0 to 59.", 0, 59),
                        "label" to text("A short label for the alarm.", maxLength = 60),
                        "days" to
                            days("Repeat on these days; leave out for once."),
                        required = listOf("hour", "minute"),
                    ),
            ),
            ToolSpec(
                name = "timer_set",
                description = "Start a countdown timer in this phone's clock app.",
                skill = Skills.REMINDERS,
                tier = 1,
                parameters =
                    params(
                        "seconds" to integer("The length of the timer in seconds.", 1, 86_400),
                        "label" to text("A short label for the timer.", maxLength = 60),
                        required = listOf("seconds"),
                    ),
            ),
            ToolSpec(
                name = "reminder_set",
                description =
                    "Remind the person on this phone at a time, with a notification that shows the text. " +
                        "Give the local date and time (YYYY-MM-DDTHH:MM, the phone's time zone) or the " +
                        "minutes from now.",
                skill = Skills.REMINDERS,
                tier = 1,
                parameters =
                    params(
                        "text" to text("What to remind about, in the person's words.", maxLength = 200),
                        "at" to text("The local date and time, YYYY-MM-DDTHH:MM.", maxLength = 16),
                        "in_minutes" to integer("Minutes from now, instead of a time.", 1, 525_600),
                        required = listOf("text"),
                    ),
                permissions = listOf(Permissions.POST_NOTIFICATIONS),
            ),
            ToolSpec(
                name = "calendar_read",
                description =
                    "Events in the calendars on this phone (Google and any other account synced to the " +
                        "phone) for a day or a few days: title, start, end, place and calendar.",
                skill = Skills.CALENDAR,
                tier = 0,
                parameters =
                    params(
                        "date" to text("The first day, YYYY-MM-DD (default today).", maxLength = 10),
                        "days" to integer("How many days from that one (default 1).", 1, 31),
                        "query" to text("Only events whose title has these words.", maxLength = 80),
                    ),
                permissions = listOf(Permissions.READ_CALENDAR),
            ),
            ToolSpec(
                name = "calendar_add",
                description =
                    "Add an event to a calendar on this phone. Give the title, the local start " +
                        "(YYYY-MM-DDTHH:MM) and the end or the length; it is read back before it is added.",
                skill = Skills.CALENDAR,
                tier = 2,
                parameters =
                    params(
                        "title" to text("The event's title.", maxLength = 120),
                        "start" to text("The local start, YYYY-MM-DDTHH:MM (or YYYY-MM-DD for all day).", maxLength = 16),
                        "end" to text("The local end, YYYY-MM-DDTHH:MM.", maxLength = 16),
                        "duration_minutes" to integer("The length in minutes, instead of an end (default 60).", 5, 1440),
                        "location" to text("Where it is.", maxLength = 120),
                        "calendar" to text("Which calendar, by its name; leave out for the main one.", maxLength = 80),
                        "all_day" to boolean("An all-day event."),
                        required = listOf("title", "start"),
                    ),
                permissions = listOf(Permissions.READ_CALENDAR, Permissions.WRITE_CALENDAR),
            ),
            ToolSpec(
                name = "app_open",
                description =
                    "Open an app on this phone by its name (YouTube, Camera, WhatsApp) or its package " +
                        "(com.google.android.youtube). Use this, never screen_act, to open an app.",
                skill = Skills.APPS,
                tier = 1,
                parameters =
                    params(
                        "name" to text("The app's name as the phone shows it.", maxLength = 60),
                        "package" to text("Or the app's package name.", maxLength = 120),
                    ),
            ),
            ToolSpec(
                name = "url_open",
                description =
                    "Open a web address on this phone. A link an app handles opens in that app: a YouTube " +
                        "link in YouTube, a Maps link in Maps. For a YouTube search use " +
                        "https://www.youtube.com/results?search_query=WORDS. Use this, never screen_act, to " +
                        "show a page, a search or a video.",
                skill = Skills.APPS,
                tier = 1,
                parameters = params("url" to text("The http or https address.", maxLength = 2000), required = listOf("url")),
            ),
            ToolSpec(
                name = "media_play",
                description =
                    "Play music, a podcast or videos by name on this phone: a song, an artist, an album, " +
                        "\"Hindi news\". Music opens in the phone's music app (or the app named); videos open " +
                        "as a YouTube search. Use this, never screen_act, to play something.",
                skill = Skills.MEDIA,
                tier = 1,
                parameters =
                    params(
                        "query" to text("What to play, in the person's words.", maxLength = 200),
                        "kind" to text("music (default) or video.", enum = listOf("music", "video")),
                        "app" to text("A music app by name, for example Spotify or YouTube Music.", maxLength = 60),
                        required = listOf("query"),
                    ),
            ),
            ToolSpec(
                name = "maps_navigate",
                description = "Start directions in this phone's maps app to a place or an address.",
                skill = Skills.APPS,
                tier = 1,
                parameters =
                    params(
                        "destination" to text("The place or the address.", maxLength = 200),
                        "mode" to text("How to travel (default drive).", enum = listOf("drive", "walk", "bike", "transit")),
                        required = listOf("destination"),
                    ),
            ),
            ToolSpec(
                name = "media_control",
                description =
                    "Control what is playing on this phone (music, podcasts, videos): play, pause, the " +
                        "next or previous track, or the volume.",
                skill = Skills.MEDIA,
                tier = 1,
                parameters =
                    params(
                        "action" to
                            text(
                                "What to do.",
                                enum = listOf("play", "pause", "toggle", "next", "previous", "volume_up", "volume_down", "mute", "unmute"),
                            ),
                        required = listOf("action"),
                    ),
            ),
            ToolSpec(
                name = "location_now",
                description =
                    "Where this phone is now: latitude, longitude, how accurate, and the address when the " +
                        "phone can tell. Read once when asked; the phone never stores it.",
                skill = Skills.LOCATION,
                tier = 0,
                parameters = params(),
                permissions = listOf(if (flavor == Flavor.PERSONAL) Permissions.FINE_LOCATION else Permissions.COARSE_LOCATION),
            ),
            ToolSpec(
                name = "settings_toggle",
                description =
                    "Change a phone setting that apps may change: the flashlight (on, off), the ringer " +
                        "(normal, vibrate, silent), the media volume (0 to 100) or Do Not Disturb (on, off). " +
                        "Android lets no app switch Wi-Fi, Bluetooth, mobile data or NFC: for those the " +
                        "phone shows their switch for the person to tap.",
                skill = Skills.SETTINGS,
                tier = 1,
                parameters =
                    params(
                        "setting" to
                            text(
                                "Which setting.",
                                enum = listOf("flashlight", "ringer", "volume", "dnd", "wifi", "bluetooth", "mobile_data", "nfc"),
                            ),
                        "value" to text("on, off, normal, vibrate, silent, or a volume 0 to 100.", maxLength = 10),
                        required = listOf("setting"),
                    ),
            ),
            ToolSpec(
                name = "screen_read",
                description =
                    "Last resort: each use needs the person's PIN. Prefer a specific tool (app_open, " +
                        "url_open, media_play, calls_recent, notifications_read...). Reads the text on this " +
                        "phone's screen now (the app in front), for what no other tool can reach.",
                skill = Skills.SCREEN,
                tier = 3,
                parameters = params("app" to text(APP_TO_FRONT, maxLength = 120)),
                special = listOf(SpecialAccess.ACCESSIBILITY),
                flavors = setOf(Flavor.PERSONAL),
            ),
            ToolSpec(
                name = "screen_act",
                description =
                    "Last resort: each use needs the person's PIN. Prefer a specific tool (app_open, " +
                        "url_open, media_play, call_place, sms_send...). Uses the phone like a person: taps a " +
                        "button or a text on the screen, types into the focused field, scrolls, or goes back, " +
                        "home or to the recent apps.",
                skill = Skills.SCREEN,
                tier = 3,
                parameters =
                    params(
                        "action" to
                            text(
                                "What to do.",
                                enum = listOf("tap", "type", "scroll_up", "scroll_down", "back", "home", "recents"),
                            ),
                        "app" to text(APP_TO_FRONT, maxLength = 120),
                        "target" to text("For tap: the words, the icon's name (Search) or the field (search box) on the screen.", maxLength = 100),
                        "text" to text("For type: the exact text to type.", maxLength = 500),
                        required = listOf("action"),
                    ),
                special = listOf(SpecialAccess.ACCESSIBILITY),
                flavors = setOf(Flavor.PERSONAL),
            ),
        )

    private const val APP_TO_FRONT =
        "The app to use, by name or package (YouTube); Ira brings it to the front first. Ira never reads or uses its own screen."

    // A small JSON Schema builder.

    private fun params(vararg properties: Pair<String, JsonObject>, required: List<String> = emptyList()): JsonObject =
        buildJsonObject {
            put("type", JsonPrimitive("object"))
            put("properties", JsonObject(properties.toMap()))
            if (required.isNotEmpty()) put("required", JsonArray(required.map { JsonPrimitive(it) }))
        }

    private fun text(description: String, maxLength: Int? = null, enum: List<String>? = null): JsonObject =
        buildJsonObject {
            put("type", JsonPrimitive("string"))
            put("description", JsonPrimitive(description))
            if (maxLength != null) put("maxLength", JsonPrimitive(maxLength))
            if (enum != null) put("enum", JsonArray(enum.map { JsonPrimitive(it) }))
        }

    private fun integer(description: String, minimum: Int, maximum: Int): JsonObject =
        buildJsonObject {
            put("type", JsonPrimitive("integer"))
            put("description", JsonPrimitive(description))
            put("minimum", JsonPrimitive(minimum))
            put("maximum", JsonPrimitive(maximum))
        }

    private fun boolean(description: String): JsonObject =
        buildJsonObject {
            put("type", JsonPrimitive("boolean"))
            put("description", JsonPrimitive(description))
        }

    private fun days(description: String): JsonObject =
        buildJsonObject {
            put("type", JsonPrimitive("array"))
            put("description", JsonPrimitive(description))
            put(
                "items",
                buildJsonObject {
                    put("type", JsonPrimitive("string"))
                    put("enum", JsonArray(Args.DAYS.map { JsonPrimitive(it) }))
                },
            )
        }
}
