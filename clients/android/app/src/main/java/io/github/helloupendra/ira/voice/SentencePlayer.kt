package io.github.helloupendra.ira.voice

import android.content.Context
import android.net.Uri
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
class SentencePlayer(context: Context, private val listener: Listener) {
    interface Listener {
        fun onSentenceStarted(turn: Int, seq: Int)

        fun onSentenceFinished(turn: Int, seq: Int)
    }

    private val audio = ConcurrentHashMap<String, ByteArray>()
    private var started: String? = null

    private val player: ExoPlayer =
        ExoPlayer.Builder(context)
            .setMediaSourceFactory(
                ProgressiveMediaSource.Factory(
                    DataSource.Factory { ByteArrayDataSource { uri -> audio[uri.toString()] ?: ByteArray(0) } },
                ),
            )
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(C.USAGE_ASSISTANT)
                    .setContentType(C.AUDIO_CONTENT_TYPE_SPEECH)
                    .build(),
                true, // music ducks while Ira speaks, and comes back after

            )
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
    }

    fun release() {
        stop()
        player.release()
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
}
