package io.github.helloupendra.ira.tools

import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.net.Uri
import android.os.SystemClock
import android.view.KeyEvent
import io.github.helloupendra.ira.core.Args
import io.github.helloupendra.ira.core.ToolFailure
import kotlinx.serialization.json.JsonElement

/** Opening apps, directions in the maps app, and what is playing. */
class AppTools(private val context: Context) {
    fun open(args: Args): JsonElement {
        val name = args.string("name", 60, required = true)!!
        val pm = context.packageManager
        // The apps on the home screen: visible through the manifest's <queries>, with no
        // need for the broad QUERY_ALL_PACKAGES permission.
        val launchable =
            pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
                .map { it.loadLabel(pm).toString() to it.activityInfo.packageName }
                .filter { it.second != context.packageName }
                .distinctBy { it.second }
        val wanted = name.lowercase()
        val match =
            launchable.firstOrNull { it.first.lowercase() == wanted }
                ?: launchable.filter { it.first.lowercase().contains(wanted) }.minByOrNull { it.first.length }
                ?: launchable.firstOrNull { wanted.contains(it.first.lowercase()) && it.first.length >= 3 }
                ?: throw ToolFailure("no app called '$name' is on the phone")
        val intent = pm.getLaunchIntentForPackage(match.second) ?: throw ToolFailure("${match.first} cannot be opened")
        val started = Launcher.start(context, intent, "open ${match.first}")
        return Results.of(
            "app" to match.first,
            "started" to started,
            "summary" to if (started) "Opened ${match.first}." else "The phone shows a notification: tap it to open ${match.first}.",
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
