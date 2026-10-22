package io.github.helloupendra.ira.tools

import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.app.SearchManager
import android.net.Uri
import android.provider.MediaStore
import android.os.SystemClock
import android.view.KeyEvent
import io.github.helloupendra.ira.core.Args
import io.github.helloupendra.ira.core.ToolFailure
import kotlinx.serialization.json.JsonElement

/** Opening apps, directions in the maps app, and what is playing. */
class AppTools(private val context: Context) {
    fun open(args: Args): JsonElement {
        val name = args.string("name", 60)
        val pkg = args.string("package", 120)
        val wanted = pkg ?: name ?: throw ToolFailure("say which app: its name or its package")
        val app = Apps.find(context, wanted) ?: throw ToolFailure("no app called '$wanted' is on the phone")
        val intent = context.packageManager.getLaunchIntentForPackage(app.pkg) ?: throw ToolFailure("${app.label} cannot be opened")
        val started = Launcher.start(context, intent, "open ${app.label}")
        return Results.of(
            "app" to app.label,
            "package" to app.pkg,
            "started" to started,
            "summary" to if (started) "Opened ${app.label}." else "The phone shows a notification: tap it to open ${app.label}.",
        )
    }

    /** A web address, in the app that handles it (a YouTube link in YouTube), else the browser. */
    fun url(args: Args): JsonElement {
        val url = Args.webUrl(args.string("url", 2000, required = true)!!)
        return openUrl(url, "open the link")
    }

    /** Music by name in the phone's music app; videos as a YouTube search. */
    fun mediaPlay(args: Args): JsonElement {
        val query = args.string("query", 200, required = true)!!
        val kind = args.choice("kind", listOf("music", "video"), "music")!!
        val appName = args.string("app", 60)
        if (kind == "music") {
            val intent =
                Intent(MediaStore.INTENT_ACTION_MEDIA_PLAY_FROM_SEARCH)
                    .putExtra(SearchManager.QUERY, query)
                    .putExtra(MediaStore.EXTRA_MEDIA_FOCUS, "vnd.android.cursor.item/*")
            appName?.let { name ->
                val app = Apps.find(context, name) ?: throw ToolFailure("no app called '$name' is on the phone")
                intent.setPackage(app.pkg)
            }
            val handler = intent.resolveActivity(context.packageManager)
            if (handler != null) {
                val label = Apps.label(context, handler.packageName) ?: "the music app"
                val started = Launcher.start(context, intent, "play $query")
                return Results.of(
                    "app" to label,
                    "started" to started,
                    "summary" to if (started) "Playing \"$query\" in $label." else "The phone shows a notification: tap it to play \"$query\".",
                )
            }
            if (appName != null) throw ToolFailure("$appName cannot play by name; try url_open or kind video")
        }
        return openUrl(Args.youtubeSearch(query), "search YouTube for $query")
    }

    private fun openUrl(url: String, tapToWhat: String): JsonElement {
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url)).addCategory(Intent.CATEGORY_BROWSABLE)
        val handler = intent.resolveActivity(context.packageManager) ?: throw ToolFailure("no app on the phone opens that address")
        val label = Apps.label(context, handler.packageName) ?: "the browser"
        val started = Launcher.start(context, intent, tapToWhat)
        return Results.of(
            "url" to url,
            "app" to label,
            "started" to started,
            "summary" to if (started) "Opened in $label." else "The phone shows a notification: tap it to $tapToWhat.",
        )
    }

    fun navigate(args: Args): JsonElement {
        val destination = args.string("destination", 200, required = true)!!
        val mode = args.choice("mode", listOf("drive", "walk", "bike", "transit"), "drive")!!
        val letter = mapOf("drive" to "d", "walk" to "w", "bike" to "b", "transit" to "r").getValue(mode)
        val google = Intent(Intent.ACTION_VIEW, Uri.parse("google.navigation:q=${Uri.encode(destination)}&mode=$letter"))
        // Any maps app: a geo search, when Google Maps is not there.
        val any = Intent(Intent.ACTION_VIEW, Uri.parse("geo:0,0?q=${Uri.encode(destination)}"))
        val intent = if (google.resolveActivity(context.packageManager) != null) google else any
        if (intent.resolveActivity(context.packageManager) == null) throw ToolFailure("there is no maps app on the phone")
        val started = Launcher.start(context, intent, "start directions to $destination")
        return Results.of(
            "destination" to destination,
            "mode" to mode,
            "started" to started,
            "summary" to if (started) "Directions to $destination." else "The phone shows a notification: tap it for directions.",
        )
    }

    fun media(args: Args): JsonElement {
        val action = args.choice("action", listOf("play", "pause", "toggle", "next", "previous", "volume_up", "volume_down", "mute", "unmute"))
            ?: throw ToolFailure("say what to do")
        val audio = context.getSystemService(AudioManager::class.java)
        when (action) {
            "play" -> key(audio, KeyEvent.KEYCODE_MEDIA_PLAY)
            "pause" -> key(audio, KeyEvent.KEYCODE_MEDIA_PAUSE)
            "toggle" -> key(audio, KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE)
            "next" -> key(audio, KeyEvent.KEYCODE_MEDIA_NEXT)
            "previous" -> key(audio, KeyEvent.KEYCODE_MEDIA_PREVIOUS)
            "volume_up" -> audio.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_RAISE, AudioManager.FLAG_SHOW_UI)
            "volume_down" -> audio.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_LOWER, AudioManager.FLAG_SHOW_UI)
            "mute" -> audio.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_MUTE, 0)
            "unmute" -> audio.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_UNMUTE, 0)
        }
        val volume = audio.getStreamVolume(AudioManager.STREAM_MUSIC) * 100 / maxOf(1, audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC))
        return Results.of("action" to action, "volume" to volume, "summary" to "Done: ${action.replace('_', ' ')}.")
    }

    private fun key(audio: AudioManager, code: Int) {
        val now = SystemClock.uptimeMillis()
        audio.dispatchMediaKeyEvent(KeyEvent(now, now, KeyEvent.ACTION_DOWN, code, 0))
        audio.dispatchMediaKeyEvent(KeyEvent(now, now, KeyEvent.ACTION_UP, code, 0))
    }
}
