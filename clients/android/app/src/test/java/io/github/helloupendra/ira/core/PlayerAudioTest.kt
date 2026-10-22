package io.github.helloupendra.ira.core

import androidx.media3.common.C
import io.github.helloupendra.ira.voice.SentencePlayer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The player's real audio attributes against the rule ExoPlayer enforces when it is built:
 * "Automatic handling of audio focus is only available for USAGE_MEDIA and USAGE_GAME".
 * (Building ExoPlayer itself needs a device; this checks what the app passes it.)
 */
class PlayerAudioTest {
    @Test
    fun `the player never asks ExoPlayer to handle focus for a non-media usage`() {
        val attributes = SentencePlayer.attributes()
        val media = attributes.usage == C.USAGE_MEDIA || attributes.usage == C.USAGE_GAME
        assertTrue("focus handling with usage ${attributes.usage} crashes ExoPlayer", !SentencePlayer.HANDLES_FOCUS || media)
    }

    @Test
    fun `Ira speaks as an assistant`() {
        val attributes = SentencePlayer.attributes()
        assertEquals(C.USAGE_ASSISTANT, attributes.usage)
        assertEquals(C.AUDIO_CONTENT_TYPE_SPEECH, attributes.contentType)
    }
}
