package io.github.helloupendra.ira.voice

import android.content.Context
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.net.Uri
import android.os.Build
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.datasource.ByteArrayDataSource
import androidx.media3.datasource.DataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import io.github.helloupendra.ira.core.SentenceAudio
import java.util.concurrent.ConcurrentHashMap

/**
 * Plays Ira's sentences (MP3, one per `audio` frame) back to back, in order, from memory.
 *
 * Each sentence becomes an item in one ExoPlayer playlist, so the next one starts as the
 * last one ends. Nothing is written to storage, and a sentence is forgotten once played.
 * Create it, and call it, on the main thread.
 */
// Playing from memory takes media3's byte-array source, which it marks as unstable API.
@androidx.annotation.OptIn(markerClass = [androidx.media3.common.util.UnstableApi::class])
class SentencePlayer(context: Context, private val listener: Listener) {
    interface Listener {
        fun onSentenceStarted(turn: Int, seq: Int)

        fun onSentenceFinished(turn: Int, seq: Int)

        /** Another sound took over (a phone call, an alarm, navigation): Ira has stopped. */
        fun onInterrupted() {}
    }

    private val audio = ConcurrentHashMap<String, ByteArray>()
    private var started: String? = null

    private val focus = AudioFocus(context) { interrupted() }

    private val player: ExoPlayer =
        ExoPlayer.Builder(context)
            .setMediaSourceFactory(
                ProgressiveMediaSource.Factory(
                    DataSource.Factory { ByteArrayDataSource { uri -> audio[uri.toString()] ?: ByteArray(0) } },
                ),
            )
            // ExoPlayer handles audio focus only for media and games; Ira's voice is an
            // assistant's, so AudioFocus asks for it instead (other sound ducks meanwhile).
            .setAudioAttributes(attributes(), HANDLES_FOCUS)
            .build()
            .apply {
                playWhenReady = true
                addListener(
                    object : Player.Listener {
                        override fun onEvents(player: Player, events: Player.Events) {
                            check()
                        }
                    },
                )
            }

    val isPlaying: Boolean
        get() = player.isPlaying || player.mediaItemCount > 0 && player.playbackState != Player.STATE_ENDED

    fun enqueue(sentences: List<SentenceAudio>) {
        focus.request()
        for (sentence in sentences) {
            val id = "${sentence.turn}:${sentence.seq}"
            val uri = "ira-audio://$id"
            audio[uri] = sentence.mp3
            player.addMediaItem(MediaItem.Builder().setUri(Uri.parse(uri)).setMediaId(id).build())
        }
        if (player.playbackState == Player.STATE_IDLE || player.playbackState == Player.STATE_ENDED) {
            player.prepare()
        }
        player.play()
    }

    /** Stop now and forget everything queued (a barge-in, or the stop button). */
    fun stop() {
        player.stop()
        player.clearMediaItems()
        audio.clear()
        started = null
        focus.abandon()
    }

    fun release() {
        stop()
        player.release()
    }

    private fun interrupted() {
        if (!isPlaying) return
        stop()
        listener.onInterrupted()
    }

    private fun check() {
        val current = player.currentMediaItem?.mediaId
        if (player.isPlaying && current != null && current != started) {
            started?.let { finished(it) }
            started = current
            parse(current)?.let { (turn, seq) -> listener.onSentenceStarted(turn, seq) }
        }
        if (player.playbackState == Player.STATE_ENDED) {
            started?.let { finished(it) }
            started = null
            player.clearMediaItems()
            audio.clear()
            focus.abandon()
        }
    }

    private fun finished(id: String) {
        audio.remove("ira-audio://$id")
        parse(id)?.let { (turn, seq) -> listener.onSentenceFinished(turn, seq) }
    }

    private fun parse(id: String): Pair<Int, Int>? {
        val parts = id.split(':')
        val turn = parts.getOrNull(0)?.toIntOrNull() ?: return null
        val seq = parts.getOrNull(1)?.toIntOrNull() ?: return null
        return turn to seq
    }

    companion object {
        /** ExoPlayer may handle focus only for USAGE_MEDIA and USAGE_GAME; this player does not ask it to. */
        const val HANDLES_FOCUS = false

        /** Ira's voice: an assistant speaking. */
        fun attributes(): AudioAttributes =
            AudioAttributes.Builder()
                .setUsage(C.USAGE_ASSISTANT)
                .setContentType(C.AUDIO_CONTENT_TYPE_SPEECH)
                .build()
    }
}

/**
 * Transient audio focus while Ira speaks: music and other sound duck, and come back when she
 * stops. Asked for by the app because ExoPlayer handles focus only for media and games. When
 * something else takes the sound for itself (a ringing phone, a call, an alarm), [onLost]
 * says so and Ira stops; a short sound that only ducks her (a notification) does not.
 */
class AudioFocus(context: Context, private val onLost: () -> Unit = {}) {
    private val manager = context.getSystemService(AudioManager::class.java)
    private var held = false
    private val request =
        AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
            .setAudioAttributes(
                android.media.AudioAttributes.Builder()
                    .setUsage(android.media.AudioAttributes.USAGE_ASSISTANT)
                    .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build(),
            )
            .setOnAudioFocusChangeListener { change ->
                if (change == AudioManager.AUDIOFOCUS_LOSS || change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT) onLost()
            }
            .build()

    fun request() {
        if (held) return
        held = manager?.requestAudioFocus(request) == AudioManager.AUDIOFOCUS_REQUEST_GRANTED
    }

    fun abandon() {
        if (!held) return
        manager?.abandonAudioFocusRequest(request)
        held = false
    }
}

/**
 * Says when the phone starts ringing or a phone call begins, so a call with Ira ends at once
 * and her microphone is off: from Android 12 through the audio mode, with no permission.
 * Before that, losing the audio focus while she speaks does it. The communication mode is
 * not counted: some phones use it for Ira's own microphone.
 */
class PhoneCalls(context: Context, private val onCall: () -> Unit) {
    private val manager = context.getSystemService(AudioManager::class.java)
    private val executor = context.mainExecutor
    private var watching: Any? = null

    /** Ringing, or on a phone call, now. */
    val busy: Boolean
        get() = manager != null && inCall(manager.mode)

    fun start() {
        if (Build.VERSION.SDK_INT < 31 || manager == null || watching != null) return
        val listener = AudioManager.OnModeChangedListener { mode -> if (inCall(mode)) onCall() }
        manager.addOnModeChangedListener(executor, listener)
        watching = listener
    }

    fun stop() {
        if (Build.VERSION.SDK_INT >= 31) (watching as? AudioManager.OnModeChangedListener)?.let { manager?.removeOnModeChangedListener(it) }
        watching = null
    }

    private fun inCall(mode: Int): Boolean = mode == AudioManager.MODE_RINGTONE || mode == AudioManager.MODE_IN_CALL
}
