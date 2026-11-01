package io.github.helloupendra.ira.core

import java.util.Locale

/** What Ira is doing while it works on an answer, in words; and each tool's receipt. */
object Steps {
    const val THINKING = "Thinking…"

    /** "Searching the web…", from the tool the server says Ira is using. */
    fun phrase(tool: String): String =
        when (tool) {
            "web_search" -> "Searching the web…"
            "news_search" -> "Looking at the news…"
            "video_find" -> "Finding a video…"
            "ai_sessions", "ai_session_detail" -> "Looking at the AI sessions on your Mac…"
            "browser_tabs" -> "Looking at your browser tabs…"
            "files_find", "file_read" -> "Looking at your files…"
            "calendar_read", "calendar_add" -> "Checking your calendar…"
            "contacts_lookup" -> "Looking in your contacts…"
            "calls_recent" -> "Checking your calls…"
            "call_place" -> "Placing the call…"
            "sms_read" -> "Reading your messages…"
            "sms_send" -> "Sending the message…"
            "notifications_read", "notification_reply" -> "Checking your notifications…"
            "reminder_set", "remind_me", "my_reminders", "alarm_set", "timer_set" -> "Setting it up…"
            "location_now", "maps_navigate" -> "Finding where you are…"
            "screen_read" -> "Reading the screen…"
            "drop_list", "drop_send" -> "Checking your Drop…"
            else -> "Working…"
        }

    /** "web search · 1.2 s": a tool done, under the answer on its way. */
    fun receipt(tool: String, seconds: Double): String {
        val name = tool.replace('_', ' ')
        val time = if (seconds < 10) String.format(Locale.US, "%.1f s", maxOf(seconds, 0.0)) else "${Math.round(seconds)} s"
        return "$name · $time"
    }

    /** The step under the label, with its seconds once it has taken 3. */
    fun line(step: String, seconds: Int): String = if (seconds >= 3) "$step $seconds s" else step
}
